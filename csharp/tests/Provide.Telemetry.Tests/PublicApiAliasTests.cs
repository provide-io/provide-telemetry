// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The <see cref="ProvideTelemetry"/> aliases are pure delegation, so each test
/// writes through one side and reads back through the other.
/// </summary>
/// <remarks>
/// Calling an alias and asserting it did not throw would pass against an alias
/// wired to the wrong domain module — which is the only interesting way this
/// file can be wrong. Crossing the facade boundary in every case is what makes
/// a mis-wiring visible.
/// </remarks>
[Collection("Telemetry")]
public class PublicApiAliasTests : IDisposable
{
    public PublicApiAliasTests() => Testing.ResetForTests();

    public void Dispose() => Testing.ResetForTests();

    [Fact]
    public void LoggerAndTracerProperties_AreTheSameSingletonsTheDomainModulesExpose()
    {
        Assert.Same(Logging.Logger, ProvideTelemetry.Logger);
        // Tracer resolves through the live generation, so identity is not
        // guaranteed; the contract is that it is usable and unnamed.
        using var span = ProvideTelemetry.Tracer.StartSpan("facade.span");
        Assert.Equal(32, span.TraceId.Length);
    }

    [Fact]
    public void ContextAliases_ReadAndWriteTheSameAsyncLocalStateAsContext()
    {
        ProvideTelemetry.BindContext(new Dictionary<string, object?> { ["tenant"] = "acme", ["drop"] = 1 });
        Assert.Equal("acme", Context.GetBoundFields()["tenant"]);

        ProvideTelemetry.UnbindContext("drop");
        Assert.False(Context.GetBoundFields().ContainsKey("drop"));

        ProvideTelemetry.BindSessionContext("sess-9");
        Assert.Equal("sess-9", Context.GetSessionID());
        Assert.Equal("sess-9", ProvideTelemetry.GetSessionID());

        ProvideTelemetry.ClearSessionContext();
        Assert.Equal("", Context.GetSessionID());

        ProvideTelemetry.ClearContext();
        Assert.Empty(Context.GetBoundFields());
    }

    [Fact]
    public void GetMeter_ProducesInstrumentsThatShareTheProcessHealthCounters()
    {
        var counter = ProvideTelemetry.GetMeter("alias").CreateCounter("alias.counter");

        counter.Add(2);

        Assert.Equal(2, counter.Value);
        Assert.Equal(1, Health.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void InjectTraceparent_UsesTheContextSetThroughTheFacade()
    {
        ProvideTelemetry.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");
        var headers = new Dictionary<string, string>();

        ProvideTelemetry.InjectTraceparent(headers);

        Assert.Equal("00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01", headers["traceparent"]);
    }

    [Fact]
    public void SamplingAliases_ShareStateWithTheSamplingModule()
    {
        ProvideTelemetry.SetSamplingPolicy(Signals.Logs, new SamplingPolicy { DefaultRate = 0.25 });

        Assert.Equal(0.25, ProvideTelemetry.GetSamplingPolicy(Signals.Logs).DefaultRate);
        Assert.Equal(0.25, Sampling.GetSamplingPolicy(Signals.Logs).DefaultRate);

        Sampling.SetSamplingPolicy(Signals.Logs, new SamplingPolicy { DefaultRate = 0.0 });
        Assert.False(ProvideTelemetry.ShouldSample(Signals.Logs, "any.event"));
    }

    [Fact]
    public void QueuePolicyAliases_ShareStateWithTheBackpressureModule()
    {
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy { LogsMaxSize = 7, TracesMaxSize = 8, MetricsMaxSize = 9 });

        var viaFacade = ProvideTelemetry.GetQueuePolicy();

        Assert.Equal(7, viaFacade.LogsMaxSize);
        Assert.Equal(8, viaFacade.TracesMaxSize);
        Assert.Equal(9, viaFacade.MetricsMaxSize);
        Assert.Equal(7, Backpressure.MaxSize(Signals.Logs));
    }

    [Fact]
    public void ExporterPolicyAliases_ShareStateWithTheResilienceModule()
    {
        ProvideTelemetry.SetExporterPolicy(Signals.Traces, new ExporterPolicy
        {
            Retries = 4,
            BackoffSeconds = 1.5,
            TimeoutSeconds = 2.5,
            FailOpen = false,
        });

        var viaFacade = ProvideTelemetry.GetExporterPolicy(Signals.Traces);

        Assert.Equal(4, viaFacade.Retries);
        Assert.Equal(1.5, viaFacade.BackoffSeconds);
        Assert.Equal(2.5, viaFacade.TimeoutSeconds);
        Assert.False(viaFacade.FailOpen);
        Assert.Equal(4, Resilience.GetExporterPolicy(Signals.Traces).Retries);
        // Untouched signals keep the schema defaults.
        Assert.Equal(0, ProvideTelemetry.GetExporterPolicy(Signals.Logs).Retries);
    }

    [Fact]
    public void CardinalityAliases_ShareStateWithTheCardinalityModule()
    {
        ProvideTelemetry.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 2, TtlSeconds = 60 });

        var limits = ProvideTelemetry.GetCardinalityLimits();
        Assert.Equal(2, limits["route"].MaxValues);
        Assert.Equal(60.0, limits["route"].TtlSeconds);
        Assert.Equal(2, Cardinality.GetCardinalityLimits()["route"].MaxValues);

        ProvideTelemetry.ClearCardinalityLimits();
        Assert.Empty(ProvideTelemetry.GetCardinalityLimits());
    }

    [Fact]
    public void PiiRuleAliases_ShareStateWithThePiiModule()
    {
        ProvideTelemetry.RegisterPIIRule(new PIIRule { Path = new[] { "user", "ssn" }, Mode = PiiModes.Drop });

        var rule = Assert.Single(ProvideTelemetry.GetPIIRules());
        Assert.Equal(new[] { "user", "ssn" }, rule.Path);
        Assert.Equal(PiiModes.Drop, rule.Mode);
        Assert.Single(Pii.GetPIIRules());

        ProvideTelemetry.ReplacePIIRules(new[]
        {
            new PIIRule { Path = new[] { "card" }, Mode = PiiModes.Hash },
        });
        var replaced = Assert.Single(ProvideTelemetry.GetPIIRules());
        Assert.Equal(PiiModes.Hash, replaced.Mode);
    }

    [Fact]
    public void SchemaAliases_ShareStateWithTheSchemaModule()
    {
        Assert.False(ProvideTelemetry.GetStrictSchema());

        ProvideTelemetry.SetStrictSchema(true);

        Assert.True(ProvideTelemetry.GetStrictSchema());
        Assert.True(Schema.GetStrictSchema());
        Assert.Throws<EventSchemaError>(() => ProvideTelemetry.Event("Order", "create", "ok"));
        Assert.Equal("order.create.ok", ProvideTelemetry.Event("order", "create", "ok").Event);
    }

    [Fact]
    public void ClassificationAliases_ShareStateWithTheClassificationModule()
    {
        ProvideTelemetry.RegisterClassificationRules(new[]
        {
            new ClassificationRule { Pattern = "ssn", Class = DataClass.Restricted },
        });
        Assert.Equal(DataClass.Restricted, Classification.ClassifyKey("ssn"));

        ProvideTelemetry.SetClassificationPolicy(new ClassificationPolicy { RestrictedAction = "hash" });

        Assert.Equal("hash", ProvideTelemetry.GetClassificationPolicy().RestrictedAction);
        Assert.Equal("hash", Classification.GetClassificationPolicy().RestrictedAction);
    }

    [Fact]
    public void ConsentAliases_ShareStateWithTheConsentModule()
    {
        ProvideTelemetry.SetConsentLevel(ConsentLevel.Minimal);

        Assert.Equal(ConsentLevel.Minimal, Consent.GetConsentLevel());
        Assert.Equal(ConsentLevel.Minimal, ProvideTelemetry.GetConsentLevel());
        Assert.True(ProvideTelemetry.ShouldAllow(Signals.Logs, "ERROR"));
        Assert.False(ProvideTelemetry.ShouldAllow(Signals.Logs, "INFO"));

        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", "FULL");
        try
        {
            ProvideTelemetry.LoadConsentFromEnv();
            Assert.Equal(ConsentLevel.Full, ProvideTelemetry.GetConsentLevel());
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", null);
        }
    }

    [Fact]
    public void RuntimeAliases_ShareStateWithSetup()
    {
        ProvideTelemetry.SetupTelemetry();

        ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides { LogLevel = "ERROR" });
        Assert.Equal("ERROR", ProvideTelemetry.GetRuntimeConfig()!.Logging.Level);
        Assert.Equal("ERROR", Setup.GetRuntimeConfig()!.Logging.Level);

        Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "DEBUG");
        try
        {
            Assert.Equal("DEBUG", ProvideTelemetry.ReloadRuntimeFromEnv().Logging.Level);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", null);
        }

        Assert.True(ProvideTelemetry.GetRuntimeStatus().SetupDone);
        ProvideTelemetry.ShutdownTelemetry();
        Assert.False(ProvideTelemetry.GetRuntimeStatus().SetupDone);
    }

    [Fact]
    public void GetTraceContext_ReturnsTheCanonicalValueStruct()
    {
        ProvideTelemetry.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");

        var value = ProvideTelemetry.GetTraceContext();

        Assert.Equal(
            new TraceContextValue("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331"), value);
    }

    [Fact]
    public void GetHealthSnapshot_ReflectsEmissionsMadeThroughTheFacade()
    {
        ProvideTelemetry.Counter("alias.health").Add(1);

        Assert.Equal(1, ProvideTelemetry.GetHealthSnapshot().MetricsEmitted);
    }
}
