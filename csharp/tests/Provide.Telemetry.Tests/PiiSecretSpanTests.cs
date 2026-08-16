// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

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
}
