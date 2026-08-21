// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace Provide.Telemetry;

/// <summary>
/// Stable error fingerprinting — a 12-char hex hash of the exception type plus
/// the top 3 stack frames, normalized to <c>basename:function</c> with no line
/// numbers so the same failure fingerprints identically across runs.
/// </summary>
/// <remarks>
/// The algorithm is the five-language contract, matching
/// <c>src/provide/telemetry/logger/processors.py</c> (<c>_compute_error_fingerprint</c>),
/// <c>typescript/src/fingerprint.ts</c>, <c>go/internal/fingerprintcore/fingerprint.go</c>, and
/// <c>rust/src/fingerprint.rs</c>: lowercase the parts, join with <c>:</c>,
/// SHA-256 the UTF-8 bytes, and keep the first 12 hex characters.
/// </remarks>
public static class Fingerprint
{
    /// <summary>Number of stack frames contributing to a fingerprint.</summary>
    public const int MaxFrames = 3;

    /// <summary>Hex characters retained from the SHA-256 digest.</summary>
    public const int FingerprintLength = 12;

    // .NET stack trace lines look like:
    //   "   at Namespace.Type.Method() in /path/to/File.cs:line 42"
    //   "   at Namespace.Type.Method()"                    (no PDB / no file info)
    // Group 1 is the fully-qualified method, group 2 the file path when present.
    private static readonly Regex FrameRe = new(
        @"^\s*at\s+(.+?)\s*(?:\(.*?\))?(?:\s+in\s+(.+?):line\s+\d+)?\s*$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>
    /// Compute the fingerprint for an exception type name and optional stack trace.
    /// </summary>
    /// <param name="errorName">Exception type name, e.g. <c>ValueError</c>.</param>
    /// <param name="stackTrace">
    /// Raw <see cref="Exception.StackTrace"/> text, or null when no stack is available.
    /// </param>
    public static string ComputeErrorFingerprint(string errorName, string? stackTrace = null)
        => ComputeErrorFingerprintFromParts(errorName, ExtractFrames(stackTrace));

    /// <summary>
    /// Compute the fingerprint from an exception type name and pre-normalized
    /// <c>basename:function</c> frame strings, mirroring Go's
    /// <c>ComputeErrorFingerprintFromParts</c>.
    /// </summary>
    public static string ComputeErrorFingerprintFromParts(string errorName, IEnumerable<string>? frameParts)
    {
        var parts = new List<string> { errorName.ToLowerInvariant() };
        if (frameParts is not null) parts.AddRange(frameParts);
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(string.Join(":", parts)));
        return Convert.ToHexStringLower(digest)[..FingerprintLength];
    }

    /// <summary>
    /// Compute the fingerprint directly from an exception.
    /// </summary>
    public static string ComputeErrorFingerprint(Exception exception)
        => ComputeErrorFingerprint(exception.GetType().Name, exception.StackTrace);

    /// <summary>
    /// Normalize the innermost <see cref="MaxFrames"/> stack frames into
    /// <c>basename:function</c> pairs. .NET orders stack traces innermost-first,
    /// so the leading frames are the ones Python and TypeScript keep with
    /// <c>[-3:]</c> / <c>slice(-3)</c> over their outermost-first traces.
    /// </summary>
    internal static List<string> ExtractFrames(string? stackTrace)
    {
        var frames = new List<string>();
        if (string.IsNullOrEmpty(stackTrace)) return frames;

        foreach (var line in stackTrace.Split('\n'))
        {
            var match = FrameRe.Match(line.TrimEnd('\r'));
            if (!match.Success) continue;

            var func = LeafFunction(match.Groups[1].Value);
            var basename = Basename(match.Groups[2].Success ? match.Groups[2].Value : "");
            if (basename.Length == 0) continue;

            frames.Add($"{basename}:{func}");
            if (frames.Count == MaxFrames) break;
        }
        return frames;
    }

    /// <summary>Strip directories and the extension, then lowercase: "/a/b/File.cs" -> "file".</summary>
    private static string Basename(string path)
    {
        var leaf = path.Replace('\\', '/').Split('/')[^1];
        var dot = leaf.LastIndexOf('.');
        return (dot > 0 ? leaf[..dot] : leaf).ToLowerInvariant();
    }

    /// <summary>Keep the final dotted segment of a qualified method name, lowercased.</summary>
    private static string LeafFunction(string qualified)
    {
        var trimmed = qualified.Trim();
        var dot = trimmed.LastIndexOf('.');
        return (dot >= 0 ? trimmed[(dot + 1)..] : trimmed).ToLowerInvariant();
    }
}
