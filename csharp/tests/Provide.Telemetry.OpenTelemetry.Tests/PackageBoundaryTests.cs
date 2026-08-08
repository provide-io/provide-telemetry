// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests;

/// <summary>
/// Asserts the split is real, against the built assemblies rather than the
/// project files — a transitive reference would satisfy a csproj grep and still
/// drag OpenTelemetry into a core-only application.
/// </summary>
[Collection("OpenTelemetry")]
public class PackageBoundaryTests
{
    [Fact]
    public void CoreAssemblyHasNoOpenTelemetryOrMicrosoftDependencyInjectionReferences()
    {
        var references = typeof(TelemetryConfig).Assembly
            .GetReferencedAssemblies()
            .Select(name => name.Name ?? "")
            .ToList();

        Assert.DoesNotContain(references, name => name.StartsWith("OpenTelemetry", StringComparison.Ordinal));
        Assert.DoesNotContain("Microsoft.Extensions.DependencyInjection", references);
        Assert.DoesNotContain("Microsoft.Extensions.Logging", references);
    }

    [Fact]
    public void IntegrationAssemblyReferencesCoreAndCoreDoesNotReferenceIntegration()
    {
        var integration = typeof(OpenTelemetryBackendRegistration).Assembly
            .GetReferencedAssemblies()
            .Select(name => name.Name ?? "")
            .ToList();
        var core = typeof(TelemetryConfig).Assembly
            .GetReferencedAssemblies()
            .Select(name => name.Name ?? "")
            .ToList();

        Assert.Contains("Provide.Telemetry", integration);
        Assert.DoesNotContain("Provide.Telemetry.OpenTelemetry", core);
    }

    [Fact]
    public void IntegrationRegistersBackendWithoutCoreReferencingIntegration()
    {
        Testing.ResetForTests();
        OpenTelemetryBackendRegistration.Register();
        var config = TelemetryConfig.Default();
        config.Tracing.OtlpEndpoint = "http://127.0.0.1:4318";

        using var backend = TelemetryBackendRegistry.Create(config);

        Assert.NotNull(backend);
        Assert.True(backend!.Providers.Traces);
    }

    [Fact]
    public void CoreRunsWithNoBackendRegistered()
    {
        // The registry starts empty in a fresh process; every facade call must
        // still work, which is the whole point of the core package shipping alone.
        Testing.ResetForTests();
        Assert.Null(Setup.CurrentBackend);
        var meter = Metrics.GetMeter("boundary");
        var counter = meter.CreateCounter("boundary.counter");
        counter.Add(1);
        Assert.Equal(1, counter.Value);
    }
}

[CollectionDefinition("OpenTelemetry", DisableParallelization = true)]
public class OpenTelemetryCollection
{
}
