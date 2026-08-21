// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Proves consent, enable gates, setup idempotency, receipts, and backpressure hold.
/// </summary>
[Collection("Telemetry")]
public class GovernanceConsentTests
{
    public GovernanceConsentTests() => Testing.ResetForTests();

    [Fact]
    public void ConsentNone_BlocksLoggerEmit()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        try
        {
            ProvideTelemetry.SetupTelemetry();
            ProvideTelemetry.SetConsentLevel(ConsentLevel.None);

            var sw = new StringWriter();
            var orig = Console.Error;
            Console.SetError(sw);
            ProvideTelemetry.GetLogger("consent").Info("consent.should.block");
            Console.SetError(orig);

            var outp = sw.ToString();
            Assert.DoesNotContain("consent.should.block", outp);
            Assert.True(string.IsNullOrWhiteSpace(outp.Trim()),
                $"expected no log output under ConsentLevel.None, got: {outp}");
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void ConsentFull_AllowsLoggerEmit()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        try
        {
            ProvideTelemetry.SetupTelemetry();
            ProvideTelemetry.SetConsentLevel(ConsentLevel.Full);

            var sw = new StringWriter();
            var orig = Console.Error;
            Console.SetError(sw);
            ProvideTelemetry.GetLogger("consent").Info("consent.should.emit");
            Console.SetError(orig);

            Assert.Contains("consent.should.emit", sw.ToString());
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void ConsentNone_BlocksTracerSpanAndMetrics()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.SetConsentLevel(ConsentLevel.None);

        var before = ProvideTelemetry.GetHealthSnapshot();

        using var span = ProvideTelemetry.GetTracer().StartSpan("consent.blocked.span");
        Assert.Equal("00000000000000000000000000000000", span.TraceId);

        var counter = ProvideTelemetry.Counter("consent.blocked.counter");
        counter.Add(5);
        Assert.Equal(0, counter.Value);

        var gauge = ProvideTelemetry.Gauge("consent.blocked.gauge");
        gauge.Set(9);
        Assert.Equal(0, gauge.Value);

        var hist = ProvideTelemetry.Histogram("consent.blocked.hist");
        hist.Record(3);
        Assert.Equal(0, hist.Count);

        var after = ProvideTelemetry.GetHealthSnapshot();
        Assert.Equal(before.TracesEmitted, after.TracesEmitted);
        Assert.Equal(before.MetricsEmitted, after.MetricsEmitted);
    }

    [Fact]
    public void ConsentMinimal_AllowsErrorLogs_BlocksInfoAndTraces()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        try
        {
            ProvideTelemetry.SetupTelemetry();
            ProvideTelemetry.SetConsentLevel(ConsentLevel.Minimal);

            var sw = new StringWriter();
            var orig = Console.Error;
            Console.SetError(sw);
            var log = ProvideTelemetry.GetLogger("consent");
            log.Info("consent.minimal.info");
            log.Warn("consent.minimal.warn");
            log.Error("consent.minimal.error");
            Console.SetError(orig);

            var outp = sw.ToString();
            Assert.DoesNotContain("consent.minimal.info", outp);
            Assert.DoesNotContain("consent.minimal.warn", outp);
            Assert.Contains("consent.minimal.error", outp);

            using var span = ProvideTelemetry.GetTracer().StartSpan("minimal.span");
            Assert.Equal("00000000000000000000000000000000", span.TraceId);
            Assert.False(ProvideTelemetry.ShouldAllow("context", ""));
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void ConsentFunctional_AllowsWarnLogs_BlocksInfoAndContext()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        try
        {
            ProvideTelemetry.SetupTelemetry();
            ProvideTelemetry.SetConsentLevel(ConsentLevel.Functional);

            var sw = new StringWriter();
            var orig = Console.Error;
            Console.SetError(sw);
            var log = ProvideTelemetry.GetLogger("consent");
            log.Info("consent.func.info");
            log.Warn("consent.func.warn");
            Console.SetError(orig);

            var outp = sw.ToString();
            Assert.DoesNotContain("consent.func.info", outp);
            Assert.Contains("consent.func.warn", outp);

            Assert.True(ProvideTelemetry.ShouldAllow("traces", ""));
            Assert.True(ProvideTelemetry.ShouldAllow("metrics", ""));
            Assert.False(ProvideTelemetry.ShouldAllow("context", ""));

            ProvideTelemetry.BindContext(new Dictionary<string, object?> { ["user_id"] = "u1" });
            Assert.Empty(Context.GetBoundFields());
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void LoadConsentFromEnv_SetsLevel()
    {
        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", "MINIMAL");
        try
        {
            ProvideTelemetry.LoadConsentFromEnv();
            Assert.Equal(ConsentLevel.Minimal, ProvideTelemetry.GetConsentLevel());
            Assert.False(ProvideTelemetry.ShouldAllow("traces", ""));
            Assert.True(ProvideTelemetry.ShouldAllow("logs", "ERROR"));
            Assert.False(ProvideTelemetry.ShouldAllow("logs", "INFO"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void SetupTelemetry_LoadsConsentFromEnv()
    {
        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", "NONE");
        try
        {
            ProvideTelemetry.SetupTelemetry();
            Assert.Equal(ConsentLevel.None, ProvideTelemetry.GetConsentLevel());
            Assert.False(ProvideTelemetry.ShouldAllow("logs", "ERROR"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void GetLogger_LazyInit_LoadsConsentFromEnv()
    {
        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", "NONE");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        try
        {
            // No SetupTelemetry: the first record a logger emits takes the lazy
            // path, which must read the env the same way the explicit path does
            // — and must do so before that very record is admitted.
            var sw = new StringWriter();
            var orig = Console.Error;
            Console.SetError(sw);
            ProvideTelemetry.GetLogger("lazy-consent").Info("lazy.consent.should.block");
            Console.SetError(orig);

            Assert.Equal(ConsentLevel.None, ProvideTelemetry.GetConsentLevel());
            Assert.False(ProvideTelemetry.ShouldAllow("logs", "ERROR"));
            Assert.DoesNotContain("lazy.consent.should.block", sw.ToString());
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", null);
            Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void SetupTelemetry_UnsetConsentEnvLeavesAProgrammaticLevelAlone()
    {
        Environment.SetEnvironmentVariable("PROVIDE_CONSENT_LEVEL", null);
        ProvideTelemetry.SetConsentLevel(ConsentLevel.Minimal);

        ProvideTelemetry.SetupTelemetry();

        Assert.Equal(ConsentLevel.Minimal, ProvideTelemetry.GetConsentLevel());
    }

    [Fact]
    public void SetupTelemetry_Idempotent_IgnoresSecondConfig()
    {
        var first = TelemetryConfig.Default();
        first.ServiceName = "first-svc";
        ProvideTelemetry.SetupTelemetry(first);

        var second = TelemetryConfig.Default();
        second.ServiceName = "second-svc";
        var returned = ProvideTelemetry.SetupTelemetry(second);

        Assert.Equal("first-svc", returned.ServiceName);
        Assert.Equal("first-svc", ProvideTelemetry.GetRuntimeConfig()?.ServiceName);
    }

    [Fact]
    public void TracingDisabled_DropsSpans()
    {
        var cfg = TelemetryConfig.Default();
        cfg.Tracing.Enabled = false;
        ProvideTelemetry.SetupTelemetry(cfg);

        using var span = ProvideTelemetry.GetTracer().StartSpan("disabled.span");
        Assert.Equal("00000000000000000000000000000000", span.TraceId);
        Assert.Equal(0, ProvideTelemetry.GetHealthSnapshot().TracesEmitted);
    }

    [Fact]
    public void MetricsDisabled_DropsInstruments()
    {
        var cfg = TelemetryConfig.Default();
        cfg.Metrics.Enabled = false;
        ProvideTelemetry.SetupTelemetry(cfg);

        var counter = ProvideTelemetry.Counter("disabled.counter");
        counter.Add(10);
        Assert.Equal(0, counter.Value);
        Assert.Equal(0, ProvideTelemetry.GetHealthSnapshot().MetricsEmitted);
    }

    [Fact]
    public void NoOpSpan_HoldsBackpressureTicketUntilDispose()
    {
        ProvideTelemetry.SetupTelemetry();
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy
        {
            LogsMaxSize = 0,
            TracesMaxSize = 1,
            MetricsMaxSize = 0,
        });

        var span1 = ProvideTelemetry.GetTracer().StartSpan("hold.one");
        Assert.NotEqual("00000000000000000000000000000000", span1.TraceId);

        // Queue full while first span lives — second should drop.
        using (var span2 = ProvideTelemetry.GetTracer().StartSpan("hold.two"))
        {
            Assert.Equal("00000000000000000000000000000000", span2.TraceId);
        }

        span1.Dispose();

        // After release, a new span can acquire.
        using var span3 = ProvideTelemetry.GetTracer().StartSpan("hold.three");
        Assert.NotEqual("00000000000000000000000000000000", span3.TraceId);
    }

    [Fact]
    public void Trace_Action_DoesNotReturnDisposedSpan()
    {
        ProvideTelemetry.SetupTelemetry();
        var ran = false;
        // Compile-time contract: Trace(Action) is void (not IDisposable).
        ProvideTelemetry.Trace("void.trace", () => { ran = true; });
        Assert.True(ran);
    }

    [Fact]
    public void Receipts_EmittedFromPiiSanitize_WithHmac()
    {
        ProvideTelemetry.EnableReceipts(true, "test-key", "receipt-svc");
        var payload = new Dictionary<string, object?>
        {
            ["password"] = "super-secret-value",
            ["ok"] = "visible",
        };
        var outp = Pii.SanitizePayload(payload, enabled: true, maxDepth: 8);
        Assert.Equal(Pii.Redacted, outp["password"]);
        Assert.Equal("visible", outp["ok"]);

        var receipts = ProvideTelemetry.GetEmittedReceiptsForTests();
        Assert.NotEmpty(receipts);
        var r = Assert.Single(receipts, x => x.FieldPath == "password");
        Assert.Equal("redact", r.Action);
        Assert.Equal("receipt-svc", r.ServiceName);
        Assert.False(string.IsNullOrEmpty(r.ReceiptId));
        Assert.False(string.IsNullOrEmpty(r.OriginalHash));
        Assert.False(string.IsNullOrEmpty(r.Hmac));
    }

    [Fact]
    public void Receipts_DisabledByDefault()
    {
        _ = Pii.SanitizePayload(
            new Dictionary<string, object?> { ["password"] = "x" },
            enabled: true,
            maxDepth: 8);
        Assert.Empty(ProvideTelemetry.GetEmittedReceiptsForTests());
    }
}
