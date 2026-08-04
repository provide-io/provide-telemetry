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
}
