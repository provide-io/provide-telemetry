// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// Host/port shape rules on OTLP endpoints — the bracket arithmetic, the
/// userinfo strip and the port range each carried surviving boundary mutants.
/// </summary>
[Collection("OpenTelemetry")]
public class EndpointShapeTests
{
    [Theory]
    [InlineData("http://collector.example:4318")]
    [InlineData("http://user:pw@collector.example")]
    [InlineData("http://[::1]:4318")]
    [InlineData("https://[2001:db8::1]/v1")]
    public void AWellShapedEndpointBuildsASignalUri(string endpoint)
    {
        Assert.NotNull(Endpoints.BuildSignalUri(endpoint, "logs"));
    }

    [Theory]
    [InlineData("http://[::1]:0")]
    [InlineData("http://[::1]:99999")]
    [InlineData("http://:4318")]
    [InlineData("http://collector.example:")]
    [InlineData("ftp://collector.example")]
    public void AMalformedHostOrPortIsRefused(string endpoint)
    {
        Assert.Throws<ConfigurationError>(() => Endpoints.BuildSignalUri(endpoint, "logs"));
    }

    [Fact]
    public void HeadersJoinWithCommasAndDeduplicateCaseInsensitively()
    {
        var formatted = Endpoints.FormatHeaders(new Dictionary<string, string>
        {
            ["Alpha"] = "1",
            ["alpha"] = "2",
            ["beta"] = "3",
        });

        Assert.Equal("Alpha=2,beta=3", formatted);
    }
}
