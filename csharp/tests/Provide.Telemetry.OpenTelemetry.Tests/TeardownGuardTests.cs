// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry.OpenTelemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// The teardown guard and deadline clamp: an exporter that throws while
/// closing must not take the application's shutdown with it, and a deadline
/// arbitrarily far in the future must clamp instead of overflowing the
/// millisecond conversion.
/// </summary>
[Collection("OpenTelemetry")]
public class TeardownGuardTests
{
    [Fact]
    public void SwallowContainsAThrowingTeardownAction()
    {
        var exception = Record.Exception(
            () => OpenTelemetryBackend.Swallow(() => throw new InvalidOperationException("exporter died closing")));

        Assert.Null(exception);
    }

    [Fact]
    public void SwallowRunsANonThrowingActionToCompletion()
    {
        var ran = false;

        OpenTelemetryBackend.Swallow(() => ran = true);

        Assert.True(ran);
    }

    [Fact]
    public void RemainingMsClampsAFarFutureDeadlineToIntMax()
    {
        Assert.Equal(int.MaxValue, OpenTelemetryBackend.RemainingMs(DateTimeOffset.MaxValue));
    }

    [Fact]
    public void RemainingMsClampsAnExpiredDeadlineToZero()
    {
        Assert.Equal(0, OpenTelemetryBackend.RemainingMs(DateTimeOffset.UtcNow.AddSeconds(-5)));
    }

    [Fact]
    public void RemainingMsReportsANearDeadlineInRange()
    {
        var ms = OpenTelemetryBackend.RemainingMs(DateTimeOffset.UtcNow.AddSeconds(10));

        Assert.InRange(ms, 1, 10_000);
    }
}
