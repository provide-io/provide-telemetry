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

    public static void RegisterSecretPattern(string name, Regex pattern)
    {
        lock (Gate) { CustomSecrets[name] = pattern; }
    }

    /// <summary>
    /// Reduce an arbitrary value to dictionaries, lists and scalars.
    /// </summary>
    /// <remarks>
    /// Runs before redaction so that lists, JSON trees and plain objects are
    /// inspectable rather than opaque. Cycles and over-deep branches collapse to
    /// <see cref="Redacted"/>.
    /// </remarks>
    public static object? Harden(object? value, int maxDepth = DefaultMaxDepth) =>
        Hardening.Harden(value, maxDepth <= 0 ? DefaultMaxDepth : maxDepth);

    public static Dictionary<string, object?> SanitizePayload(
        IReadOnlyDictionary<string, object?> payload,
        bool enabled,
        int maxDepth)
    {
        ArgumentNullException.ThrowIfNull(payload);
        var (sanitized, redactions) = SanitizeHardened(HardenPayload(payload, maxDepth), enabled);
        Receipts.RecordAll(redactions);
        return sanitized;
    }

    /// <summary>Harden a payload without redacting it — the pipeline's hardening stage.</summary>
    internal static Dictionary<string, object?> HardenPayload(
        IReadOnlyDictionary<string, object?> payload, int maxDepth)
    {
        var depth = maxDepth <= 0 ? DefaultMaxDepth : maxDepth;
        return Hardening.Harden(payload, depth) as Dictionary<string, object?>
               ?? new Dictionary<string, object?>(StringComparer.Ordinal);
    }

    /// <summary>
    /// Redact an already-hardened payload — the pipeline's pii stage.
    /// </summary>
    /// <remarks>
    /// Takes no depth: hardening already applied it, and a second limit here
    /// could only disagree with the first.
    /// </remarks>
    internal static (Dictionary<string, object?> Payload, IReadOnlyList<PendingRedaction> Redactions)
        SanitizeHardened(Dictionary<string, object?> hardened, bool enabled)
    {
        if (!enabled) return (hardened, Array.Empty<PendingRedaction>());

        var (rules, custom) = SnapshotRules();

        var redactions = new List<PendingRedaction>();
        var context = new SanitizeContext(rules, custom, redactions);
        return (SanitizeMap(hardened, context, Array.Empty<string>()), redactions);
    }

    /// <summary>Copy the registered rules and custom patterns under the lock.</summary>
    /// <remarks>
    /// A pass works from a snapshot so a concurrent <c>RegisterPIIRule</c> cannot
    /// change the rule set halfway through one payload. Returning the pair rather
    /// than assigning two locals inside the lock also leaves nothing
    /// conditionally assigned: a mutant of either copy compiles instead of
    /// taking the whole type out of the mutation score.
    /// </remarks>
    private static (List<PIIRule> Rules, Dictionary<string, Regex> Custom) SnapshotRules()
    {
        lock (Gate)
        {
            return (
                _rules.Select(CloneRule).ToList(),
                new Dictionary<string, Regex>(CustomSecrets, StringComparer.Ordinal));
        }
    }

    /// <summary>Rules, patterns and the receipt log for one sanitize pass.</summary>
    private sealed record SanitizeContext(
        List<PIIRule> Rules,
        Dictionary<string, Regex> Custom,
        List<PendingRedaction> Redactions);

    /// <summary>
    /// How many slash-separated parts a span needs before its shape reads as a path.
    /// </summary>
    private const int PathMinSegments = 3;

    /// <summary>
    /// True when a matched span is a filesystem path rather than a secret.
    /// </summary>
    /// <remarks>
    /// The long_base64 pattern is [A-Za-z0-9+/]{40,} and "/" belongs to the
    /// base64 alphabet, so any deep path of unpunctuated segments matched it:
    /// /home/deploy/apps/production/current/lib/service is 48 characters of pure
    /// base64 alphabet holding no secret. Narrowing the charset is not the fix —
    /// dropping "/" costs 44% of detections on 32-byte secrets, because a 44-char
    /// base64 string containing one slash cannot be told from a path by charset.
    /// Shape separates them: a path carries several short all-lowercase words
    /// (usr, local, lib), which random base64 effectively never produces.
    /// </remarks>
    internal static bool LooksLikePath(string span)
    {
        var segments = span.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Length < PathMinSegments) return false;
        var wordy = 0;
        foreach (var segment in segments)
        {
            var allLower = segment.Length > 0;
            foreach (var c in segment)
            {
                if (c is < 'a' or > 'z') { allLower = false; break; }
            }
            if (allLower) wordy++;
        }
        return wordy * 2 >= segments.Length;
    }

    /// <summary>
    /// Every secret-looking span in <paramref name="text"/>, widened to whole
    /// tokens, sorted and coalesced.
    /// </summary>
    /// <remarks>
    /// Every pattern is scanned across the WHOLE value, not stopped at its
    /// first match, and every pattern is tried even after one has hit.
    /// Skipping either leaks. Stopping a pattern at its first match let a path
    /// shadow a real secret: long_base64 matches a path first, suppressing
    /// that match as path-shaped moved the scan to the next pattern, and
    /// long_base64 is the last one, so the credential behind the path was
    /// never looked for. Stopping at the first pattern to hit left a field's
    /// second and third secrets in the log, which whole-value blanking used to
    /// cover for free.
    /// <para>
    /// A single Match runs first as a fast path: a clean value, which is
    /// nearly every log field, allocates no list, because the all-matches walk
    /// is only entered once a pattern is known to match.
    /// </para>
    /// </remarks>
    private static List<(int Start, int End)> SecretSpans(string text, Dictionary<string, Regex> custom)
    {
        var spans = new List<(int Start, int End)>();
        if (string.IsNullOrEmpty(text) || text.Length < MinSecretLength) return spans;
        foreach (var re in BuiltinSecrets) Collect(re, text, spans);
        foreach (var re in custom.Values) Collect(re, text, spans);
        return MergeSpans(spans);
    }

    private static void Collect(Regex re, string text, List<(int Start, int End)> spans)
    {
        var first = re.Match(text);
        if (!first.Success) return;
        for (var m = first; m.Success; m = m.NextMatch())
        {
            // A registered pattern that can match the empty string carries no
            // secret; widening a zero-length match to its token would redact a
            // word for nothing. NextMatch steps past an empty match itself, so
            // skipping here cannot loop.
            if (m.Length == 0) continue;
            if (!LooksLikePath(m.Value)) spans.Add(ExpandToToken(text, m.Index, m.Index + m.Length));
        }
    }

    /// <summary>
    /// Widen a match to its whitespace-delimited token.
    /// </summary>
    /// <remarks>
    /// Redacting the literal match alone can leave part of a credential
    /// behind: the jwt pattern matches header.payload, and a JWT has THREE
    /// dot-separated parts, so the signature would survive. Whitespace is the
    /// boundary a secret cannot cross without ceasing to be one token.
    /// </remarks>
    private static (int Start, int End) ExpandToToken(string text, int start, int end)
    {
        while (start > 0 && !char.IsWhiteSpace(text[start - 1])) start--;
        while (end < text.Length && !char.IsWhiteSpace(text[end])) end++;
        return (start, end);
    }

    /// <summary>
    /// Sort and coalesce overlapping spans so each region is replaced once.
    /// Two patterns can match the same credential -- long_base64 and jwt both
    /// hit a JWT -- and after widening they overlap exactly, which would
    /// otherwise emit "******".
    /// </summary>
    private static List<(int Start, int End)> MergeSpans(List<(int Start, int End)> spans)
    {
        if (spans.Count < 2) return spans;
        spans.Sort((a, b) => a.Start.CompareTo(b.Start));
        var merged = new List<(int Start, int End)>(spans.Count);
        foreach (var span in spans)
        {
            if (merged.Count > 0 && span.Start <= merged[^1].End)
            {
                merged[^1] = (merged[^1].Start, Math.Max(merged[^1].End, span.End));
                continue;
            }
            merged.Add(span);
        }
        return merged;
    }

    /// <summary>
    /// Replace every secret-looking token of <paramref name="text"/>.
    /// </summary>
    /// <remarks>
    /// The match is widened to its whitespace-delimited token first. Redacting
    /// the literal match alone can leave part of a credential behind: the jwt
    /// pattern matches header.payload, and a JWT has THREE dot-separated parts,
    /// so the signature would survive. Whitespace is the boundary a secret
    /// cannot cross without ceasing to be one token.
    /// </remarks>
    public static string RedactSecretSpans(string text)
    {
        var (_, custom) = SnapshotRules();
        return RedactSecretSpans(text, custom);
    }

    private static string RedactSecretSpans(string text, Dictionary<string, Regex> custom)
    {
        var spans = SecretSpans(text, custom);
        return spans.Count == 0 ? text : ReplaceSpans(text, spans);
    }

    /// <summary>Swap each span for the redaction sentinel.</summary>
    private static string ReplaceSpans(string text, List<(int Start, int End)> spans)
    {
        var builder = new StringBuilder(text.Length);
        var previousEnd = 0;
        foreach (var (start, end) in spans)
        {
            builder.Append(text, previousEnd, start - previousEnd);
            builder.Append(Redacted);
            previousEnd = end;
        }
        builder.Append(text, previousEnd, text.Length - previousEnd);
        return builder.ToString();
    }

    public static bool DetectSecretInValue(string text)
    {
        var (_, custom) = SnapshotRules();
        return SecretSpans(text, custom).Count > 0;
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

    private static Dictionary<string, object?> SanitizeMap(
        Dictionary<string, object?> payload,
        SanitizeContext context,
        IReadOnlyList<string> path)
    {
        var result = new Dictionary<string, object?>(StringComparer.Ordinal);
        foreach (var (key, value) in payload)
        {
            var childPath = path.Append(key).ToArray();
            var (keep, sanitized) = SanitizeValue(key, value, context, childPath);
            if (keep) result[key] = sanitized;
        }
        return result;
    }

    /// <summary>
    /// Redact one already-hardened value.
    /// </summary>
    /// <remarks>
    /// List elements inherit their container's path rather than gaining an index
    /// segment, so a rule written for <c>request.body</c> applies to every entry
    /// of a list at that path instead of to none of them.
    /// </remarks>
    private static (bool Keep, object? Value) SanitizeValue(
        string key,
        object? value,
        SanitizeContext context,
        IReadOnlyList<string> path)
    {
        var fieldPath = string.Join(".", path);
        foreach (var rule in context.Rules)
        {
            if (!PathMatches(rule.Path, path)) continue;
            return ApplyMode(value, rule.Mode, rule.TruncateTo, fieldPath, context);
        }

        if (DefaultSensitiveKeys.Contains(key))
        {
            return (true, Redact(value, fieldPath, context));
        }

        if (value is string s)
        {
            // Span-scoped: only the credential token is replaced, so the rest
            // of the string stays readable. A sensitive KEY still blanks
            // wholesale above, where the entire value is the secret.
            // One scan, not two: detecting and then redacting ran the whole
            // pattern sweep twice for every value carrying a credential.
            var spans = SecretSpans(s, context.Custom);
            if (spans.Count == 0) return (true, value);
            Redact(value, fieldPath, context);
            return (true, ReplaceSpans(s, spans));
        }

        if (value is Dictionary<string, object?> nested)
        {
            return (true, SanitizeMap(nested, context, path));
        }

        if (value is List<object?> sequence)
        {
            var sanitized = new List<object?>(sequence.Count);
            foreach (var item in sequence)
            {
                var (keep, element) = SanitizeValue(key, item, context, path);
                if (keep) sanitized.Add(element);
            }
            return (true, sanitized);
        }

        return (true, value);
    }

    private static object Redact(object? value, string fieldPath, SanitizeContext context)
    {
        // An already-redacted value earns no receipt: re-redacting the sentinel
        // would log an audit record for a change that did not happen.
        if (!Equals(value, Redacted))
        {
            context.Redactions.Add(new PendingRedaction(fieldPath, PiiModes.Redact, value));
        }
        return Redacted;
    }

    private static (bool Keep, object? Value) ApplyMode(
        object? value, string mode, int truncateTo, string fieldPath, SanitizeContext context)
    {
        switch (mode)
        {
            case PiiModes.Drop:
                context.Redactions.Add(new PendingRedaction(fieldPath, PiiModes.Drop, value));
                return (false, null);
            case PiiModes.Hash:
                context.Redactions.Add(new PendingRedaction(fieldPath, PiiModes.Hash, value));
                return (true, HashValue(value));
            case PiiModes.Truncate:
                {
                    var text = value is string s
                        ? s
                        : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "";
                    if (truncateTo <= 0 || text.Length <= truncateTo) return (true, text);
                    context.Redactions.Add(new PendingRedaction(fieldPath, PiiModes.Truncate, value));
                    return (true, text[..truncateTo] + TruncationSuffix);
                }
            case PiiModes.Pass:
                return (true, value);
            default:
                return (true, Redact(value, fieldPath, context));
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

    private static PIIRule CloneRule(PIIRule r) => new()
    {
        Path = r.Path.ToArray(),
        Mode = r.Mode,
        TruncateTo = r.TruncateTo,
    };
}
