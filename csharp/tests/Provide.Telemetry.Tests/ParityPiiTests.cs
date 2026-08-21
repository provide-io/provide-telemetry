// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Security.Cryptography;
using System.Text;
using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ParityPiiTests
{
    public ParityPiiTests() => Testing.ResetForTests();

    [Fact]
    public void PiiHash_Format()
    {
        var hash = Pii.HashValue("user-42");
        Assert.Equal(12, hash.Length);
        Assert.Matches("^[0-9a-f]{12}$", hash);
    }

    [Fact]
    public void PiiHash_Deterministic()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "uid" }, Mode = PiiModes.Hash } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["uid"] = "same-input" }, true, 32);
        Assert.Equal("f52c2013103b", r["uid"]);
    }

    [Fact]
    public void PiiHash_Integer()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "n" }, Mode = PiiModes.Hash } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["n"] = 42 }, true, 32);
        Assert.Equal("73475cb40a56", r["n"]);
    }

    // Non-string values hash their RFC 8785 canonical JSON, so the digest is
    // the same in every SDK: sha256("true"), not sha256("True").
    [Fact]
    public void PiiHash_Boolean_CanonicalJson()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "flag" }, Mode = PiiModes.Hash } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["flag"] = true }, true, 32);
        Assert.Equal("b5bea41b6c62", r["flag"]);
    }

    [Fact]
    public void PiiHash_Null_CanonicalJson()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "gone" }, Mode = PiiModes.Hash } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["gone"] = null }, true, 32);
        Assert.Equal("74234e98afe7", r["gone"]);
        Assert.Equal("74234e98afe7", Pii.HashValue(null));
    }

    [Fact]
    public void PiiHash_Float_CanonicalJson()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "ratio" }, Mode = PiiModes.Hash } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["ratio"] = 1.5 }, true, 32);
        Assert.Equal("9f29a130438b", r["ratio"]);
    }

    [Fact]
    public void PiiHash_Object_KeySortedCanonicalJson()
    {
        // Keys are registered out of order; the canonical form sorts them, so
        // the digest is sha256('{"a":"x","b":1}').
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "obj" }, Mode = PiiModes.Hash } });
        var payload = new Dictionary<string, object?>
        {
            ["obj"] = new Dictionary<string, object?> { ["b"] = 1, ["a"] = "x" },
        };
        var r = Pii.SanitizePayload(payload, true, 32);
        Assert.Equal("cdab067e9f3b", r["obj"]);
    }

    [Fact]
    public void PiiTruncate_LongerThanLimit()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = 5 } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["note"] = "hello world" }, true, 32);
        Assert.Equal("hello...", r["note"]);
    }

    [Fact]
    public void PiiTruncate_AtLimit_Unchanged()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = 5 } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["note"] = "hello" }, true, 32);
        Assert.Equal("hello", r["note"]);
    }

    [Fact]
    public void PiiTruncate_UnsetLimit_DefaultsToEight()
    {
        // TruncateTo deliberately omitted: the rule is registered without a limit.
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["note"] = "abcdefghij" }, true, 32);
        Assert.Equal("abcdefgh...", r["note"]);
    }

    [Fact]
    public void PiiTruncate_ZeroLimit_KeepsOnlyTheSuffix()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = 0 } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["note"] = "hello" }, true, 32);
        Assert.Equal("...", r["note"]);
    }

    [Fact]
    public void PiiTruncate_NegativeLimit_ClampsToZero()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = -3 } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["note"] = "hello" }, true, 32);
        Assert.Equal("...", r["note"]);
    }

    [Fact]
    public void PiiTruncate_CountsUnicodeScalarValues()
    {
        // Five astral code points; a UTF-16 slice of three would split the
        // second emoji in half.
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "note" }, Mode = PiiModes.Truncate, TruncateTo = 3 } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["note"] = "😀😀😀😀😀" }, true, 32);
        Assert.Equal("😀😀😀...", r["note"]);
    }

    [Fact]
    public void PiiRedact_SensitiveKey()
    {
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["password"] = "s3cret" }, true, 32);
        Assert.Equal("***", r["password"]);
    }

    [Fact]
    public void PiiRedact_CaseInsensitive()
    {
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["API_KEY"] = "abc123" }, true, 32);
        Assert.Equal("***", r["API_KEY"]);
    }

    [Fact]
    public void PiiDrop_RemovesKey()
    {
        ProvideTelemetry.ReplacePIIRules(new[] { new PIIRule { Path = new[] { "secret_data" }, Mode = PiiModes.Drop } });
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["secret_data"] = "top-secret", ["keep"] = "visible" }, true, 0);
        Assert.False(r.ContainsKey("secret_data"));
        Assert.Equal("visible", r["keep"]);
    }

    [Fact]
    public void SecretDetection_AWSKey()
    {
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["data"] = "AKIAIOSFODNN7EXAMPLE" }, true, 0);
        Assert.Equal("***", r["data"]);
    }

    [Fact]
    public void SecretDetection_JWT()
    {
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["data"] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0" }, true, 0);
        Assert.Equal("***", r["data"]);
    }

    [Fact]
    public void SecretDetection_GitHubToken()
    {
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["data"] = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklm" }, true, 0);
        Assert.Equal("***", r["data"]);
    }

    [Fact]
    public void PiiDepth_Nested()
    {
        var nested = new Dictionary<string, object?>
        {
            ["l1"] = new Dictionary<string, object?>
            {
                ["l2"] = new Dictionary<string, object?> { ["password"] = "x" },
            },
        };
        var r = Pii.SanitizePayload(nested, true, 8);
        var l1 = Assert.IsType<Dictionary<string, object?>>(r["l1"]);
        var l2 = Assert.IsType<Dictionary<string, object?>>(l1["l2"]);
        Assert.Equal("***", l2["password"]);
    }

    // ── default_sensitive_keys ───────────────────────────────────────────────
    // The canonical list is 17 names, matched case-insensitively. Asserting one
    // key proves nothing about the other sixteen, so the whole list is pinned —
    // dropping a name from the default set has to fail here.

    private static readonly string[] CanonicalKeys =
    [
        "password", "passwd", "secret", "token", "api_key", "apikey", "auth", "authorization",
        "credential", "private_key", "ssn", "credit_card", "creditcard", "cvv", "pin",
        "account_number", "cookie",
    ];

    public static TheoryData<string> CanonicalSensitiveKeys()
    {
        var data = new TheoryData<string>();
        foreach (var key in CanonicalKeys) data.Add(key);
        return data;
    }

    [Theory]
    [MemberData(nameof(CanonicalSensitiveKeys))]
    public void DefaultSensitiveKeys_AreRedacted(string key)
    {
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { [key] = "sensitive" }, true, 8);
        Assert.Equal("***", r[key]);
    }

    [Fact]
    public void DefaultSensitiveKeys_MatchCaseInsensitively()
    {
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["PassWord"] = "x" }, true, 8);
        Assert.Equal("***", r["PassWord"]);
    }

    [Fact]
    public void DefaultSensitiveKeys_ListIsExactlySeventeen()
    {
        // Guards the other direction: an over-broad default set redacts fields
        // the contract says to leave alone.
        Assert.Equal(17, CanonicalKeys.Length);
        var r = Pii.SanitizePayload(new Dictionary<string, object?> { ["username"] = "tim" }, true, 8);
        Assert.Equal("tim", r["username"]);
    }

    /// <summary>
    /// Mirrors spec/behavioral_fixtures.yaml secret_span_redaction. The cases
    /// that matter are the ones a single-span implementation gets wrong: a
    /// value holding two secrets, and a secret sitting behind a filesystem
    /// path that the base64 rule matches first.
    /// </summary>
    [Theory]
    // surrounding words survive
    [InlineData("token AKIAIOSFODNN7EXAMPLE leaked", "token *** leaked")]
    // every secret goes, not only the first
    [InlineData("first AKIAIOSFODNN7EXAMPLE second AKIAIOSFODNN7EXAMPLB", "first *** second ***")]
    // a suppressed path does not shadow the secret behind it
    [InlineData(
        "/home/deploy/apps/production/current/lib/service c2VjcmV0a2V5MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3A",
        "/home/deploy/apps/production/current/lib/service ***")]
    // no secret, no change
    [InlineData(
        "make -C /home/deploy/apps/production/current/native/capture install",
        "make -C /home/deploy/apps/production/current/native/capture install")]
    public void SecretSpanRedaction(string input, string expected)
    {
        var result = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["data"] = input }, true, 32);
        Assert.Equal(expected, result["data"]);
    }
}
