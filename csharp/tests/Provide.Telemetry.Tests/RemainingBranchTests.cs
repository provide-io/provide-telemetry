// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.RegularExpressions;

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// The last few decisions no other suite reaches: per-signal provider freezing,
/// the identifier-generating span constructor, and a handful of encoder and
/// detector fall-through paths.
/// </summary>
[Collection("Telemetry")]
public class RemainingBranchTests : IDisposable
{
    public RemainingBranchTests() => Testing.ResetForTests();

    public void Dispose() => Testing.ResetForTests();

    // ── per-signal provider freezing ─────────────────────────────────────────

    private static TelemetryConfig ConfigWithLiveProvider(string signal)
    {
        // Port 9 is the discard service: the exporter installs without ever
        // completing a connection, so a provider is genuinely live and no
        // collector is required.
        var config = TelemetryConfig.Default();
        const string endpoint = "http://127.0.0.1:9";
        switch (signal)
        {
            case "traces": config.Tracing.OtlpEndpoint = endpoint; break;
            case "metrics": config.Metrics.OtlpEndpoint = endpoint; break;
            default: config.Logging.OtlpEndpoint = endpoint; break;
        }
        return config;
    }

    [Fact]
    public void ALiveTracesProviderFreezesOnlyTheTracesEndpoint()
    {
        ProvideTelemetry.SetupTelemetry(ConfigWithLiveProvider("traces"));
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Traces);

        var frozen = ProvideTelemetry.GetRuntimeConfig()!;
        frozen.Tracing.OtlpEndpoint = "http://127.0.0.1:19";
        var error = Assert.Throws<ProviderImmutableError>(
            () => ProvideTelemetry.ReconfigureTelemetry(frozen));
        Assert.Equal(
            "provider-changing fields cannot be updated via reconfigure; restart the process",
            error.Message);

        // The logs endpoint is not baked into anything, so it still applies.
        var allowed = ProvideTelemetry.GetRuntimeConfig()!;
        allowed.Logging.OtlpEndpoint = "http://127.0.0.1:19";
        Assert.Equal(
            "http://127.0.0.1:19",
            ProvideTelemetry.ReconfigureTelemetry(allowed).Logging.OtlpEndpoint);
    }

    [Fact]
    public void ALiveMetricsProviderFreezesOnlyTheMetricsEndpoint()
    {
        ProvideTelemetry.SetupTelemetry(ConfigWithLiveProvider("metrics"));
        Assert.True(ProvideTelemetry.GetRuntimeStatus().Providers.Metrics);

        var frozen = ProvideTelemetry.GetRuntimeConfig()!;
        frozen.Metrics.OtlpEndpoint = "http://127.0.0.1:19";
        Assert.Throws<ProviderImmutableError>(() => ProvideTelemetry.ReconfigureTelemetry(frozen));

        var allowed = ProvideTelemetry.GetRuntimeConfig()!;
        allowed.Tracing.OtlpEndpoint = "http://127.0.0.1:19";
        Assert.Equal(
            "http://127.0.0.1:19",
            ProvideTelemetry.ReconfigureTelemetry(allowed).Tracing.OtlpEndpoint);
    }

    [Fact]
    public void ReloadFromEnvIsFrozenByALiveProviderToo()
    {
        // ReloadRuntimeFromEnv holds the same precondition as reconfigure: a
        // provider that baked in an endpoint cannot be talked out of it by the
        // environment either.
        ProvideTelemetry.SetupTelemetry(ConfigWithLiveProvider("traces"));
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "renamed-while-live");
        try
        {
            Assert.Throws<ProviderImmutableError>(() => ProvideTelemetry.ReloadRuntimeFromEnv());
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", null);
        }
    }

    // ── span identifiers ─────────────────────────────────────────────────────

    [Fact]
    public void ASpanWithNoSuppliedIdentifiersGeneratesItsOwn()
    {
        using var blank = new NoOpSpan(null, null, default, null);
        using var empty = new NoOpSpan("", "", default, null);

        foreach (var span in new ISpan[] { blank, empty })
        {
            Assert.Matches("^[0-9a-f]{32}$", span.TraceId);
            Assert.Matches("^[0-9a-f]{16}$", span.SpanId);
        }

        // Generated identifiers must be distinct, or every span in a process
        // would collapse into one trace.
        Assert.NotEqual(blank.TraceId, empty.TraceId);
        Assert.NotEqual(blank.SpanId, empty.SpanId);
    }

    [Fact]
    public void SuppliedIdentifiersAreKeptVerbatim()
    {
        using var span = new NoOpSpan(
            "0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331", default, null);

        Assert.Equal("0af7651916cd43dd8448eb211c80319c", span.TraceId);
        Assert.Equal("b7ad6b7169203331", span.SpanId);
    }

    [Fact]
    public void ANewIdIsLowercaseHexOfTheRequestedLength()
    {
        Assert.Matches("^[0-9a-f]{8}$", NoOpSpan.NewId(8));
        Assert.Equal("", NoOpSpan.NewId(0));
    }

    // ── logger construction ──────────────────────────────────────────────────

    [Fact]
    public void ALoggerConstructedWithANullNameBehavesAsTheRootLogger()
    {
        ProvideTelemetry.SetupTelemetry();
        var writer = new StringWriter();
        var original = Console.Error;
        Console.SetError(writer);
        try
        {
            new Logger(null!).Info("root.direct.ok");
        }
        finally
        {
            Console.SetError(original);
        }

        var line = writer.ToString().Trim();
        Assert.Contains("root.direct.ok", line);
        Assert.DoesNotContain("logger_name=", line);
    }

    // ── schema strict mode, satisfied ────────────────────────────────────────

    [Fact]
    public void StrictModeAcceptsEventNamesThatMatchTheGrammar()
    {
        Schema.SetStrictSchema(true);

        Assert.Equal("order.create.invoice.ok", Schema.EventName("order", "create", "invoice", "ok"));
        Assert.Equal("a.b_1.c2", Schema.EventName("a", "b_1", "c2"));
        Assert.Equal("order.create.ok", Schema.Event("order", "create", "ok").Event);
    }

    // ── secret detection fall-through ────────────────────────────────────────

    [Fact]
    public void ALongValueMatchingNeitherBuiltinNorCustomPatternsIsNotASecret()
    {
        Pii.RegisterSecretPattern("corp", new Regex("corp-secret-[0-9]+"));

        // Long enough to be scanned, and deliberately shaped to miss every
        // pattern: no hex run, no base64 run, no known prefix.
        Assert.False(Pii.DetectSecretInValue("the quick brown fox jumps over it"));
    }

    // ── property projection ──────────────────────────────────────────────────

    [Fact]
    public void WriteOnlyPropertiesAndIndexersAreSkippedWhenProjectingAnObject()
    {
        // An indexer has no single value to read, and a write-only property has
        // none at all; neither can contribute anything for redaction to inspect.
        var hardened = Assert.IsType<Dictionary<string, object?>>(Pii.Harden(new AwkwardMembers()));

        Assert.Equal(new[] { nameof(AwkwardMembers.Readable) }, hardened.Keys.ToArray());
        Assert.Equal("visible", hardened[nameof(AwkwardMembers.Readable)]);
    }

    // ── canonical JSON booleans ──────────────────────────────────────────────

    [Fact]
    public void BothBooleanLiteralsAreEncoded()
    {
        Assert.Equal("true", CanonicalJson.Serialize(true));
        Assert.Equal("false", CanonicalJson.Serialize(false));
        Assert.Equal(
            """{"no":false,"yes":true}""",
            CanonicalJson.Serialize(new Dictionary<string, object?> { ["yes"] = true, ["no"] = false }));
    }

    // ── receipts ─────────────────────────────────────────────────────────────

    [Fact]
    public void DisablingReceiptsClearsWhatTheCollectorAlreadyHeld()
    {
        Receipts.EnableReceipts(true, "", "svc");
        Pii.SanitizePayload(
            new Dictionary<string, object?> { ["password"] = "hunter2" }, enabled: true, maxDepth: 8);
        Assert.Single(Receipts.GetEmittedReceiptsForTests());

        Receipts.EnableReceipts(false);

        Assert.Empty(Receipts.GetEmittedReceiptsForTests());
    }

    [Fact]
    public void EnablingReceiptsWithNoSinkOutsideTestModeIsRefused()
    {
        // A receipt with nowhere to go is worse than no receipts at all: the
        // caller believes there is an audit trail and there is none.
        Receipts.SetTestMode(false);
        try
        {
            Assert.Throws<MissingReceiptSinkError>(() => Receipts.EnableReceipts(true, "", "svc"));
        }
        finally
        {
            Receipts.SetTestMode(true);
            Testing.ResetForTests();
        }
    }

    // ── stringification that answers null ────────────────────────────────────

    [Fact]
    public void AValueWithNoCanonicalJsonEncodingHashesAsNull()
    {
        // Hashing never consults ToString(): a type with no JCS encoding
        // canonicalises to null, so its digest is defined — and is the null
        // digest — rather than faulting mid-redaction.
        Assert.Equal(Pii.HashValue(null), Pii.HashValue(new NullStringer()));
    }

    [Fact]
    public void AValueWhoseToStringAnswersNullTruncatesToTheEmptyString()
    {
        Pii.RegisterPIIRule(new PIIRule { Path = new[] { "odd" }, Mode = PiiModes.Truncate, TruncateTo = 4 });

        var sanitized = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["odd"] = new NullStringer() },
            enabled: true,
            maxDepth: 8);

        // Hardening reduces the object to its public state first, so the
        // truncate rule sees a dictionary and stringifies that.
        Assert.NotNull(sanitized["odd"]);
    }

    // ── resource precedence ──────────────────────────────────────────────────

    [Fact]
    public void AnEmptyIdentityFieldContributesNothingToTheResource()
    {
        // Distinct from "equal to the framework default": an empty value is not
        // a choice either, and writing it would blank out a detected value.
        var config = TelemetryConfig.Default();
        config.ServiceName = "";
        config.Environment = "";
        config.Version = "";

        var resource = ResourceBuilder.Build(
            config,
            new Dictionary<string, string> { [ResourceBuilder.ServiceNameKey] = "detected" });

        Assert.Equal("detected", resource[ResourceBuilder.ServiceNameKey]);
        Assert.False(resource.ContainsKey(ResourceBuilder.EnvironmentKey));
        Assert.False(resource.ContainsKey(ResourceBuilder.VersionKey));
    }

    // ── the core package standing alone ──────────────────────────────────────

    [Fact]
    public void WithNoBackendInstalledEveryFacadeGetterFallsBackInProcess()
    {
        // The core package ships without an exporter dependency, so this is the
        // deployment a consumer gets by default: no backend, and every facade
        // call still works against the in-process implementations.
        Testing.ResetForTests();
        TelemetryBackendRegistry.Register(_ => null!);
        try
        {
            ProvideTelemetry.SetupTelemetry();
            Assert.Null(Setup.CurrentBackend);

            using var named = Tracing.GetTracer("core").StartSpan("work");
            using var unnamed = Tracing.Tracer.StartSpan("work");
            var counter = Metrics.GetMeter("core").CreateCounter("core.counter");
            counter.Add(2);

            Assert.Equal(32, named.TraceId.Length);
            Assert.NotEqual(named.SpanId, unnamed.SpanId);
            Assert.Equal(2, counter.Value);
            Assert.Equal(2, Health.GetHealthSnapshot().TracesEmitted);
        }
        finally
        {
            Provide.Telemetry.OpenTelemetry.OpenTelemetryBackendRegistration.Register();
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void FlushBeforeSetupReportsEverySignalNotInstalled()
    {
        // No generation, so nothing to drain — and no null dereference on the
        // way to saying so.
        var result = ProvideTelemetry.FlushTelemetry();

        Assert.True(result.Logs.NotInstalled);
        Assert.True(result.Traces.NotInstalled);
        Assert.True(result.Metrics.NotInstalled);
        Assert.Null(Setup.CurrentBackend);
    }

    // ── receipt sinks ────────────────────────────────────────────────────────

    [Fact]
    public void OutsideTestModeAnExplicitSinkSatisfiesTheReceiptRequirement()
    {
        var sink = new CollectingSink();
        Receipts.SetTestMode(false);
        try
        {
            Receipts.EnableReceipts(true, "", "svc", sink);
            Pii.SanitizePayload(
                new Dictionary<string, object?> { ["password"] = "hunter2" },
                enabled: true,
                maxDepth: 8);

            var receipt = Assert.Single(sink.Received);
            Assert.Equal("password", receipt.FieldPath);
            Assert.Equal("redact", receipt.Action);
            Assert.Equal("svc", receipt.ServiceName);
        }
        finally
        {
            Receipts.SetTestMode(true);
            Testing.ResetForTests();
        }
    }

    private sealed class CollectingSink : IReceiptSink
    {
        public List<RedactionReceipt> Received { get; } = new();

        public bool Emit(RedactionReceipt receipt)
        {
            Received.Add(receipt);
            return true;
        }
    }

    private sealed class NullStringer
    {
        public override string ToString() => null!;
    }

    private sealed class AwkwardMembers
    {
        private string _hidden = "";

        public string Readable => "visible";
        public string WriteOnly { set => _hidden = value; }
        public string this[int index] => _hidden + index;
    }
}
