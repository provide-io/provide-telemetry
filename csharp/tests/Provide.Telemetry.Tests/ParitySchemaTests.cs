// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ParitySchemaTests
{
    public ParitySchemaTests() => Testing.ResetForTests();

    [Fact]
    public void EventDars_ThreeSegments()
    {
        var e = ProvideTelemetry.Event("auth", "login", "success");
        Assert.Equal("auth.login.success", e.Event);
        Assert.Equal("auth", e.Domain);
        Assert.Equal("login", e.Action);
        Assert.Equal("success", e.Status);
        Assert.Equal("", e.Resource);
    }

    [Fact]
    public void EventDars_FourSegments()
    {
        var e = ProvideTelemetry.Event("auth", "login", "user", "success");
        Assert.Equal("auth.login.user.success", e.Event);
        Assert.Equal("user", e.Resource);
    }

    [Fact]
    public void SchemaStrictMode_RejectsBadSegment()
    {
        ProvideTelemetry.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => ProvideTelemetry.Event("Auth", "login", "ok"));
    }

    [Fact]
    public void SchemaLenient_AllowsMixedCase()
    {
        ProvideTelemetry.SetStrictSchema(false);
        var e = ProvideTelemetry.Event("Auth", "Login", "Ok");
        Assert.Equal("Auth.Login.Ok", e.Event);
    }
}
