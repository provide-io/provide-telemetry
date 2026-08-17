// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.RegularExpressions;
using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Span-scoped secret redaction and the filesystem-path guard.
/// </summary>
[Collection("Telemetry")]
public class PiiSecretSpanTests
{
    public PiiSecretSpanTests() => Testing.ResetForTests();

    [Fact]
    public void RemovesTheWholeCredentialWhenThePatternMatchesOnlyPartOfIt()
    {
        // The jwt pattern matches header.payload; a JWT has THREE dot-separated
        // parts, so redacting the literal match alone would publish the signature.
        const string jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            + ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c";
        var signature = jwt[(jwt.LastIndexOf('.') + 1)..];

        var redacted = Pii.RedactSecretSpans($"auth header {jwt} rejected");

        Assert.DoesNotContain(signature, redacted);
        Assert.Equal("auth header *** rejected", redacted);
    }

    [Theory]
    // [A-Za-z0-9+/]{40,} includes the slash, so a deep path of unpunctuated
    // segments matched the base64 rule and the whole field became "***".
    [InlineData("/home/deploy/apps/production/current/lib/service")]
    [InlineData("/var/lib/docker/overlay2/abcdef0123456789/merged/app")]
    [InlineData("make -C /home/deploy/apps/production/current/native/capture install")]
    [InlineData("/private/var/folders/sg/wy47gw996f78fznt898m8x540000gn/T/pytest-of-tim")]
    public void LeavesFilesystemPathsAlone(string line)
    {
        Assert.Equal(line, Pii.RedactSecretSpans(line));
        Assert.False(Pii.DetectSecretInValue(line));
    }

    [Theory]
    // A real base64 secret, and a slash-bearing one whose segments are long and
    // wordless — neither has the shape of a path.
    [InlineData("GstpFvsHIiSVR91i5FLxOKZ8mNRZ5EifnBQR2i6bOhs=")]
    [InlineData("abcdefghij/klmnopqrst/uvwxyzABCD/EFGHIJKLMN/OPQRSTUVWX")]
    public void StillDetectsRealBase64Secrets(string secret)
    {
        Assert.True(Pii.DetectSecretInValue(secret));
        Assert.Equal("***", Pii.RedactSecretSpans(secret));
    }

    [Fact]
    public void RedactsEverySecretInAValue()
    {
        // Whole-value blanking covered every credential in a field for free.
        // Scoping redaction to one token dropped that guarantee silently: the
        // field is still flagged, but only the first secret goes.
        const string first = "AKIAIOSFODNN7EXAMPLE";
        const string second = "AKIAIOSFODNN7EXAMPLB";
        Assert.True(Pii.DetectSecretInValue(first));
        Assert.True(Pii.DetectSecretInValue(second));

        var redacted = Pii.RedactSecretSpans($"first {first} second {second}");

        Assert.DoesNotContain(first, redacted);
        Assert.DoesNotContain(second, redacted);
        Assert.Equal("first *** second ***", redacted);
    }

    [Fact]
    public void DoesNotLetAPathShadowASecretLaterInTheValue()
    {
        // long_base64 matches the path first. Suppressing that match as
        // path-shaped moved the scan on to the next pattern, and long_base64
        // is the last one, so the real secret behind the path was never looked
        // for. A path prefix must not be a redaction bypass.
        const string path = "/home/deploy/apps/production/current/lib/service";
        const string secret = "c2VjcmV0a2V5MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3A";
        Assert.False(Pii.DetectSecretInValue(path));
        Assert.True(Pii.DetectSecretInValue(secret));

        var redacted = Pii.RedactSecretSpans($"{path} {secret}");

        Assert.DoesNotContain(secret, redacted);
        Assert.Equal($"{path} ***", redacted);
    }

    [Fact]
    public void EmptyMatchingPatternRedactsNothing()
    {
        // Scanning every match means a pattern that can match the empty string
        // yields one at every position. Without a guard the walk widens a
        // zero-length match to whatever token it landed in, blanking a word
        // that holds no secret.
        Pii.RegisterSecretPattern("empty_matcher", new Regex("Z*"));
        const string clean = "the quick brown fox jumps over it";

        Assert.Equal(clean, Pii.RedactSecretSpans(clean));
    }

    [Fact]
    public void OverlappingMatchesAreRedactedOnce()
    {
        // Two patterns can hit the same token -- aws_key on the AKIA prefix and
        // long_hex on the trailing run -- and after widening both cover the
        // whole token. Without coalescing the spans the token would be replaced
        // twice and emit "******".
        const string token = "AKIAIOSFODNN7EXAMPLE0123456789abcdef0123456789abcdef";

        Assert.Equal("***", Pii.RedactSecretSpans(token));
        Assert.Equal("a *** b", Pii.RedactSecretSpans($"a {token} b"));
    }

    /// <summary>
    /// Pins both halves of the path-shape test: the segment-count floor at its
    /// boundary (two segments is not enough, three is), and the wordy-segment
    /// ratio at its boundary (exactly half is enough, and long wordless
    /// segments are base64 rather than directories).
    /// </summary>
    /// <remarks>
    /// Ported from tests/hardening/test_secret_span_redaction.py, which had
    /// these from the start while the other runtimes went without.
    /// </remarks>
    [Theory]
    // two segments is below the floor, however wordy
    [InlineData("usr/local", false)]
    // long wordless segments are base64
    [InlineData("ABCDEFGHIJ/1234567890/KLMNOPQRST", false)]
    // three short lowercase words is the smallest thing that reads as a path
    [InlineData("usr/local/lib", true)]
    // exactly half wordy is enough; the ratio test is >=, not >
    [InlineData("usr/local/AB12/CD34", true)]
    // one word in three is a minority; the ratio is a product, not a sum
    [InlineData("usr/AB12/CD34", false)]
    public void LooksLikePathScoresSegmentShape(string span, bool expected)
    {
        Assert.Equal(expected, Pii.LooksLikePath(span));
    }
}
