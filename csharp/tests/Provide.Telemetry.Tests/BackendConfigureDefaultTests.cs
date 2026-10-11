// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>A backend written before <c>Configure</c> existed still compiles and reports no failure.</summary>
public class BackendConfigureDefaultTests
{
    private sealed class MinimalBackend : ITelemetryBackend
    {
        public ProviderFlags Providers => ProviderFlags.None;
        public ITracer? GetTracer(string name) => null;
        public IMeter? GetMeter(string name) => null;
        public void EmitLog(CanonicalLogRecord record) { }
        public FlushResult Flush(DateTimeOffset deadline) => new();
        public void Shutdown(DateTimeOffset deadline) { }
        public void Dispose() { }
    }

    [Fact]
    public void Configure_DefaultsToNoFailure()
    {
        using ITelemetryBackend backend = new MinimalBackend();
        Assert.Equal("", backend.Configure(TelemetryConfig.Default()));
    }
}
