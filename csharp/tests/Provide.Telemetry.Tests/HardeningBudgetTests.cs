// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Collections;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Hardening accepts arbitrary IEnumerable from the caller's log fields, so a
/// lazy iterator can be infinite, huge, or throw mid-stream. These tests pin
/// the element budget and the containment rule: over-budget sequences truncate
/// visibly, and any iterator failure reduces the value instead of faulting the
/// caller's log statement.
/// </summary>
public class HardeningBudgetTests
{
    private static IEnumerable<int> Endless()
    {
        var i = 0;
        while (true) yield return i++;
    }

    private static IEnumerable<int> ThrowsMidStream()
    {
        yield return 1;
        yield return 2;
        throw new InvalidOperationException("iterator bomb");
    }

    private sealed class IoFailingSequence : IEnumerable<int>
    {
        public IEnumerator<int> GetEnumerator() => throw new IOException("device gone");
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }

    [Fact]
    public void AnInfiniteIteratorIsTruncatedAtTheBudgetWithAVisibleSentinel()
    {
        var list = Assert.IsType<List<object?>>(Pii.Harden(Endless()));

        Assert.Equal(Hardening.MaxSequenceElements + 1, list.Count);
        Assert.Equal(Pii.Redacted, list[^1]);
        Assert.Equal(0, list[0]);
        Assert.Equal(Hardening.MaxSequenceElements - 1, list[Hardening.MaxSequenceElements - 1]);
    }

    [Fact]
    public void ASequenceExactlyAtTheBudgetIsKeptWholeWithNoSentinel()
    {
        var source = Enumerable.Range(0, Hardening.MaxSequenceElements).ToList();

        var list = Assert.IsType<List<object?>>(Pii.Harden(source));

        Assert.Equal(Hardening.MaxSequenceElements, list.Count);
        Assert.DoesNotContain(Pii.Redacted, list);
    }

    [Fact]
    public void ASequenceOnePastTheBudgetTruncatesWithTheSentinel()
    {
        var source = Enumerable.Range(0, Hardening.MaxSequenceElements + 1).ToList();

        var list = Assert.IsType<List<object?>>(Pii.Harden(source));

        Assert.Equal(Hardening.MaxSequenceElements + 1, list.Count);
        Assert.Equal(Pii.Redacted, list[^1]);
    }

    [Fact]
    public void AnIteratorThrowingMidStreamReducesTheWholeSequence()
    {
        Assert.Equal(Pii.Redacted, Pii.Harden(ThrowsMidStream()));
    }

    [Fact]
    public void AnEnumeratorFailingWithAnArbitraryExceptionReducesTheValue()
    {
        // Beyond the historic NotSupportedException/TargetInvocationException
        // pair: any escape from iteration must become a reduction, not a
        // faulted log call.
        Assert.Equal(Pii.Redacted, Pii.Harden(new IoFailingSequence()));
    }

    [Fact]
    public void AThrowingIteratorInsideAPayloadReducesOnlyThatField()
    {
        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["bad"] = ThrowsMidStream(), ["good"] = "kept" },
            enabled: true,
            maxDepth: 8);

        Assert.Equal(Pii.Redacted, sanitized["bad"]);
        Assert.Equal("kept", sanitized["good"]);
    }
}
