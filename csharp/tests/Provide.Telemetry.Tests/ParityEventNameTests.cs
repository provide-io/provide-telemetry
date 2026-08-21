// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Executable evidence for the event_name_contract fixtures in
/// spec/behavioral_fixtures.yaml — one fact per case, in fixture order.
/// </summary>
[Collection("Telemetry")]
public sealed class ParityEventNameTests : IDisposable
{
    public ParityEventNameTests() => Schema.SetStrictSchema(false);

    public void Dispose() => Schema.SetStrictSchema(false);

    [Fact]
    public void EventName_RelaxedSingleSegment_Ok()
        => Assert.Equal("startup", Schema.EventName("startup"));

    [Fact]
    public void EventName_RelaxedTwoSegments_Ok()
        => Assert.Equal("app.ready", Schema.EventName("app", "ready"));

    [Fact]
    public void EventName_RelaxedSixSegments_Ok()
        => Assert.Equal("a.b.c.d.e.f", Schema.EventName("a", "b", "c", "d", "e", "f"));

    [Fact]
    public void EventName_RelaxedGrammarNotEnforced_Ok()
        => Assert.Equal("User.Login-OK", Schema.EventName("User", "Login-OK"));

    [Fact]
    public void EventName_RelaxedZeroSegments_Throws()
        => Assert.Throws<EventSchemaError>(() => Schema.EventName());

    [Fact]
    public void EventName_RelaxedEmptySegment_Throws()
        => Assert.Throws<EventSchemaError>(() => Schema.EventName("user", "", "ok"));

    [Fact]
    public void EventName_StrictThreeSegments_Ok()
    {
        Schema.SetStrictSchema(true);
        Assert.Equal("user.login.ok", Schema.EventName("user", "login", "ok"));
    }

    [Fact]
    public void EventName_StrictFiveSegments_Ok()
    {
        Schema.SetStrictSchema(true);
        Assert.Equal("a.b.c.d.e", Schema.EventName("a", "b", "c", "d", "e"));
    }

    [Fact]
    public void EventName_StrictTwoSegments_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.EventName("too", "few"));
    }

    [Fact]
    public void EventName_StrictSixSegments_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.EventName("a", "b", "c", "d", "e", "f"));
    }

    [Fact]
    public void EventName_StrictGrammarEnforced_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.EventName("user", "Login", "ok"));
    }

    [Fact]
    public void EventName_StrictZeroSegments_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.EventName());
    }

    [Fact]
    public void ValidateEventName_RelaxedSingleSegment_Ok()
        => Schema.ValidateEventName("startup");

    [Fact]
    public void ValidateEventName_RelaxedEmptyString_Throws()
        => Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName(""));

    [Fact]
    public void ValidateEventName_RelaxedInteriorEmptySegment_Throws()
        => Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName("a..b"));

    /// <summary>
    /// The C#-only defect: ValidateEventName applied the segment grammar on
    /// every call without ever reading GetStrictSchema(), so relaxed mode was
    /// strict here and relaxed in its sibling EventName.
    /// </summary>
    [Fact]
    public void ValidateEventName_RelaxedGrammarNotEnforced_Ok()
        => Schema.ValidateEventName("User.Login-OK");

    [Fact]
    public void ValidateEventName_StrictGrammarEnforced_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName("user.Login.ok"));
    }

    [Fact]
    public void ValidateEventName_StrictTwoSegments_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName("too.few"));
    }

    /// <summary>
    /// Event() is out of scope for the 2026-08-20 contract change: its count
    /// rule belongs to the DAS/DARS record shape, not to the name.
    /// </summary>
    [Fact]
    public void Event_CountRuleUnchangedByRelaxedMode_Throws()
    {
        Assert.Throws<EventSchemaError>(() => Schema.Event("only", "two"));
        Assert.Throws<EventSchemaError>(() => Schema.Event("a", "b", "c", "d", "e"));
    }
}
