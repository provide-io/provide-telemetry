// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The event-schema surface: segment arity, the strict-mode segment grammar,
/// and required-key enforcement.
/// </summary>
/// <remarks>
/// Every rejection asserts the message as well as the type. The messages carry
/// the offending value, which is the only thing that makes a schema complaint
/// actionable from a log line, and a silently reworded message is a regression
/// the type alone would not catch.
/// </remarks>
[Collection("Telemetry")]
public class SchemaValidationTests
{
    public SchemaValidationTests() => Testing.ResetForTests();

    // ── Schema.Event: DAS / DARS ─────────────────────────────────────────────

    [Fact]
    public void Event_ThreeSegments_IsDomainActionStatusWithNoResource()
    {
        var record = Schema.Event("order", "create", "success");

        Assert.Equal("order.create.success", record.Event);
        Assert.Equal("order", record.Domain);
        Assert.Equal("create", record.Action);
        Assert.Equal("success", record.Status);
        Assert.Equal("", record.Resource);
    }

    [Fact]
    public void Event_FourSegments_PutsTheThirdInResourceAndTheFourthInStatus()
    {
        var record = Schema.Event("order", "create", "invoice", "failed");

        Assert.Equal("order.create.invoice.failed", record.Event);
        Assert.Equal("invoice", record.Resource);
        Assert.Equal("failed", record.Status);
    }

    [Theory]
    [InlineData(2)]
    [InlineData(5)]
    public void Event_RejectsArityOutsideThreeOrFour(int count)
    {
        var segments = Enumerable.Repeat("seg", count).ToArray();

        var error = Assert.Throws<EventSchemaError>(() => Schema.Event(segments));
        Assert.Equal($"event requires 3 (DAS) or 4 (DARS) segments, got {count}", error.Message);
    }

    [Fact]
    public void Event_StrictMode_RejectsASegmentOutsideTheGrammarAndNamesIt()
    {
        Schema.SetStrictSchema(true);

        var error = Assert.Throws<EventSchemaError>(() => Schema.Event("order", "Create", "success"));
        Assert.Equal("invalid event segment: Create", error.Message);
    }

    [Fact]
    public void Event_LenientMode_AcceptsSegmentsStrictModeWouldReject()
    {
        // Strictness is opt-in: the default runtime must not start rejecting
        // event names a service has been emitting for years.
        Assert.False(Schema.GetStrictSchema());
        Assert.Equal("Order.CREATE.9ok", Schema.Event("Order", "CREATE", "9ok").Event);
    }

    // ── Schema.EventName ─────────────────────────────────────────────────────

    [Theory]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(5)]
    public void EventName_JoinsThreeToFiveSegmentsWithDots(int count)
    {
        var segments = Enumerable.Range(0, count).Select(i => $"s{i}").ToArray();

        Assert.Equal(string.Join(".", segments), Schema.EventName(segments));
    }

    // Strict mode as of 2026-08-20: the 3-5 count is now a strict-mode rule, so
    // relaxed mode no longer reaches this comparison at all.
    [Theory]
    [InlineData(2)]
    [InlineData(6)]
    public void EventName_StrictMode_RejectsArityOutsideThreeToFive(int count)
    {
        Schema.SetStrictSchema(true);
        var segments = Enumerable.Repeat("seg", count).ToArray();

        var error = Assert.Throws<EventSchemaError>(() => Schema.EventName(segments));
        Assert.Equal($"event name requires 3-5 segments, got {count}", error.Message);
    }

    // The relaxed side of the same boundary: no upper bound, a floor of one, and
    // an empty segment still rejected. The old count check was the only thing
    // rejecting an empty segment, so this case used to pass.
    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(6)]
    public void EventName_LenientMode_AcceptsAnyNonEmptyArity(int count)
    {
        var segments = Enumerable.Repeat("seg", count).ToArray();

        Assert.Equal(string.Join(".", segments), Schema.EventName(segments));
    }

    [Fact]
    public void EventName_LenientMode_RejectsZeroSegments()
    {
        var error = Assert.Throws<EventSchemaError>(() => Schema.EventName());
        Assert.Equal("event name requires at least 1 segment, got 0", error.Message);
    }

    [Fact]
    public void EventName_LenientMode_RejectsAnEmptySegment()
    {
        var error = Assert.Throws<EventSchemaError>(() => Schema.EventName("order", "", "ok"));
        Assert.Equal("event name segments must be non-empty", error.Message);
    }

    [Fact]
    public void EventName_StrictMode_RejectsASegmentOutsideTheGrammar()
    {
        Schema.SetStrictSchema(true);

        var error = Assert.Throws<EventSchemaError>(() => Schema.EventName("order", "create", "OK"));
        Assert.Equal("invalid event segment: OK", error.Message);
    }

    [Fact]
    public void EventName_LenientMode_LeavesSegmentsUnchecked()
    {
        Assert.Equal("Order.Create.OK", Schema.EventName("Order", "Create", "OK"));
    }

    // ── Schema.ValidateEventName ─────────────────────────────────────────────

    [Theory]
    [InlineData("order.create.success")]
    [InlineData("order.create.invoice.success")]
    [InlineData("a.b_1.c2.d.e")]
    public void ValidateEventName_AcceptsThreeToFiveLowercaseSegments(string message)
    {
        Schema.ValidateEventName(message);
    }

    // Strict mode as of 2026-08-20, for the same reason as
    // EventName_StrictMode_RejectsArityOutsideThreeToFive.
    [Theory]
    [InlineData("order.create", 2)]
    [InlineData("a.b.c.d.e.f", 6)]
    public void ValidateEventName_StrictMode_RejectsArityOutsideThreeToFive(string message, int parts)
    {
        Schema.SetStrictSchema(true);

        var error = Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName(message));
        Assert.Equal($"event name requires 3-5 segments, got {parts}", error.Message);
    }

    [Theory]
    [InlineData("startup")]
    [InlineData("order.create")]
    [InlineData("a.b.c.d.e.f")]
    public void ValidateEventName_LenientMode_AcceptsAnyNonEmptyArity(string message)
    {
        Schema.ValidateEventName(message);
    }

    // "" splits to one empty segment, never zero segments, so the empty-segment
    // rule is what rejects an empty name.
    [Theory]
    [InlineData("")]
    [InlineData("a..b")]
    public void ValidateEventName_LenientMode_RejectsAnEmptySegment(string message)
    {
        var error = Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName(message));
        Assert.Equal("event name segments must be non-empty", error.Message);
    }

    [Theory]
    // Leading digit, uppercase, and a hyphen: the grammar is ^[a-z][a-z0-9_]*$
    // and each of these violates a different part of it. The empty-segment case
    // moved to ValidateEventName_LenientMode_RejectsAnEmptySegment, because an
    // empty segment is now rejected before the grammar is consulted and carries
    // its own message.
    [InlineData("order.create.Success", "Success")]
    [InlineData("order.1create.success", "1create")]
    [InlineData("order.create-thing.success", "create-thing")]
    public void ValidateEventName_StrictMode_ChecksTheGrammarAndNamesTheBadSegment(
        string message, string offender)
    {
        // Changed on 2026-08-20. This method used to apply the grammar on every
        // call without reading GetStrictSchema — a deliberate C# choice ("a
        // caller reaching for the validator has already asked for the check"),
        // but one no other language made, so relaxed mode was strict here and
        // relaxed in its sibling EventName. The five-language contract now wins.
        Schema.SetStrictSchema(true);

        var error = Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName(message));
        Assert.Equal($"invalid event segment: {offender}", error.Message);
    }

    [Theory]
    [InlineData("order.create.Success")]
    [InlineData("order.1create.success")]
    [InlineData("order.create-thing.success")]
    public void ValidateEventName_LenientMode_LeavesTheGrammarUnchecked(string message)
    {
        Assert.False(Schema.GetStrictSchema());

        Schema.ValidateEventName(message);
    }

    // ── Schema.ValidateRequiredKeys ──────────────────────────────────────────

    [Fact]
    public void ValidateRequiredKeys_PassesWhenEveryKeyIsPresent()
    {
        var attrs = new Dictionary<string, object?> { ["user_id"] = "u1", ["tenant"] = "t1" };

        Schema.ValidateRequiredKeys(attrs, new[] { "user_id", "tenant" });
    }

    [Fact]
    public void ValidateRequiredKeys_NamesTheFirstMissingKey()
    {
        var attrs = new Dictionary<string, object?> { ["user_id"] = "u1" };

        var error = Assert.Throws<EventSchemaError>(
            () => Schema.ValidateRequiredKeys(attrs, new[] { "user_id", "tenant", "region" }));
        Assert.Equal("missing required key: tenant", error.Message);
    }

    [Fact]
    public void ValidateRequiredKeys_TreatsAPresentNullValueAsPresent()
    {
        // Presence is about the key, not the value: a deliberately null field is
        // still a field the caller supplied.
        var attrs = new Dictionary<string, object?> { ["tenant"] = null };

        Schema.ValidateRequiredKeys(attrs, new[] { "tenant" });
    }

    [Fact]
    public void ValidateRequiredKeys_EmptyRequirementListAcceptsAnything()
    {
        Schema.ValidateRequiredKeys(new Dictionary<string, object?>(), Array.Empty<string>());
    }

    // ── strict-mode toggle ───────────────────────────────────────────────────

    [Fact]
    public void StrictSchema_RoundTripsAndResetsToLenient()
    {
        Schema.SetStrictSchema(true);
        Assert.True(Schema.GetStrictSchema());

        Testing.ResetForTests();

        Assert.False(Schema.GetStrictSchema());
    }
}
