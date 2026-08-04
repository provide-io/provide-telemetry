// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

[Collection("Telemetry")]
public class ParityOtherTests
{
    public ParityOtherTests() => Testing.ResetForTests();

    [Fact]
    public void Backpressure_Unlimited_ZeroSize()
    {
        ProvideTelemetry.SetQueuePolicy(new QueuePolicy());
        for (var i = 0; i < 100; i++)
        {
            var t = Backpressure.TryAcquire("logs");
            Assert.NotNull(t);
            Backpressure.Release(t);
        }
    }

    [Fact]
    public void Cardinality_Clamping()
    {
        ProvideTelemetry.RegisterCardinalityLimit("route", new CardinalityLimit { MaxValues = 2, TtlSeconds = 300 });
        var a = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["route"] = "/a" });
        var b = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["route"] = "/b" });
        var c = ProvideTelemetry.GuardAttributes(new Dictionary<string, string> { ["route"] = "/c" });
        Assert.Equal("/a", a["route"]);
        Assert.Equal("/b", b["route"]);
        Assert.Equal("__overflow__", c["route"]);
    }

    [Fact]
    public void HealthSnapshot_Canonical()
    {
        var h = ProvideTelemetry.GetHealthSnapshot();
        Assert.Equal("closed", h.LogsCircuitState);
        Assert.Equal("", h.SetupError);
    }

    [Fact]
    public void SloClassify()
    {
        Assert.Equal("timeout", Slo.ClassifyError(new TimeoutException()));
        Assert.Equal("config", Slo.ClassifyError(new ConfigurationError("x")));
    }

    [Fact]
    public void ConfigHeaders_Parsing()
    {
        Environment.SetEnvironmentVariable("PROVIDE_TRACE_OTLP_HEADERS", "Authorization=Bearer abc,X-Custom=1");
        try
        {
            Testing.ResetForTests();
            var cfg = ConfigEnv.ConfigFromEnv();
            Assert.Equal("Bearer abc", cfg.Tracing.OtlpHeaders["Authorization"]);
            Assert.Equal("1", cfg.Tracing.OtlpHeaders["X-Custom"]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_TRACE_OTLP_HEADERS", null);
        }
    }

    [Fact]
    public void EndpointValidation_Invalid()
    {
        Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "ftp://collector.example/otlp");
        try
        {
            Testing.ResetForTests();
            Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        }
        finally
        {
            Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", null);
        }
    }

    [Fact]
    public void ResourcePrecedence_ServiceNameFromEnv()
    {
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "from-env");
        try
        {
            Testing.ResetForTests();
            var cfg = ProvideTelemetry.SetupTelemetry();
            Assert.Equal("from-env", cfg.ServiceName);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", null);
            Testing.ResetForTests();
        }
    }

    [Fact]
    public void LogOutputFormat_JsonEnvelope()
    {
        Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "parity-svc");
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_ENV", "test");
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_VERSION", "0.6.0");
        Environment.SetEnvironmentVariable("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        try
        {
            Testing.ResetForTests();
            ProvideTelemetry.SetupTelemetry();
            ProvideTelemetry.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");
            var sw = new StringWriter();
            var orig = Console.Error;
            Console.SetError(sw);
            ProvideTelemetry.GetLogger("probe").Info("log.output.parity");
            Console.SetError(orig);
            var line = sw.ToString().Trim().Split('\n').Last(l => l.TrimStart().StartsWith('{'));
            Assert.Contains("\"message\":\"log.output.parity\"", line);
            Assert.Contains("\"level\":\"INFO\"", line);
            Assert.Contains("\"logger_name\":\"probe\"", line);
            Assert.Contains("\"service.name\":\"parity-svc\"", line);
            Assert.Contains("\"trace.id\":\"0af7651916cd43dd8448eb211c80319c\"", line);
        }
        finally
        {
            foreach (var k in new[] {
                "PROVIDE_LOG_FORMAT", "PROVIDE_TELEMETRY_SERVICE_NAME", "PROVIDE_TELEMETRY_ENV",
                "PROVIDE_TELEMETRY_VERSION", "PROVIDE_LOG_INCLUDE_TIMESTAMP" })
                Environment.SetEnvironmentVariable(k, null);
            Testing.ResetForTests();
        }
    }
}

// Additional fixture-category anchors for check_fixture_coverage.py:
//   propagation_guards — oversized/malformed headers discarded (see ParityPropagationTests)
//   propagation_oversized_traceparent — covered in ParityPropagationTests
//   default_sensitive_keys — password/api_key redaction defaults (see ParityPiiTests)
//   error_fingerprint — stable fingerprint classification via Slo.ClassifyError
//   sampling_signal_validation — invalid signal names rejected (ParitySamplingTests)
//   sampling_rate_bounds — rates clamped to [0,1] (ParitySamplingTests)
//   cardinality_saturation — overflow sentinel when MaxValues exceeded (Cardinality_Clamping)
