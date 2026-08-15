// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Pins the literal-valued config surfaces the mutation report showed were
/// asserted by nothing: every env-var name must reach its field, every DTO
/// default must hold its documented value, and the redaction map must carry
/// its canonical keys. A mutated name or default here changed no test before.
/// </summary>
[Collection("Telemetry")]
public class ConfigLiteralPinTests : IDisposable
{
    private static readonly string[] Vars =
    {
        "PROVIDE_TELEMETRY_SERVICE_NAME", "PROVIDE_TELEMETRY_ENV", "PROVIDE_TELEMETRY_VERSION",
        "PROVIDE_TELEMETRY_STRICT_SCHEMA", "PROVIDE_TELEMETRY_STRICT_EVENT_NAME",
        "PROVIDE_TELEMETRY_REQUIRED_KEYS", "PROVIDE_LOG_LEVEL", "PROVIDE_LOG_FORMAT",
        "PROVIDE_LOG_INCLUDE_TIMESTAMP", "PROVIDE_LOG_INCLUDE_CALLER", "PROVIDE_LOG_SANITIZE",
        "PROVIDE_LOG_PII_MAX_DEPTH", "PROVIDE_LOG_OTLP_ENABLED", "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "PROVIDE_TRACE_ENABLED", "PROVIDE_TRACE_SAMPLE_RATE", "PROVIDE_METRICS_ENABLED",
        "PROVIDE_SAMPLING_LOGS_RATE", "PROVIDE_SAMPLING_TRACES_RATE", "PROVIDE_SAMPLING_METRICS_RATE",
        "PROVIDE_EXPORTER_LOGS_RETRIES", "PROVIDE_EXPORTER_LOGS_FAIL_OPEN",
        "PROVIDE_EXPORTER_TRACES_RETRIES", "PROVIDE_EXPORTER_TRACES_FAIL_OPEN",
        "PROVIDE_EXPORTER_METRICS_RETRIES", "PROVIDE_EXPORTER_METRICS_FAIL_OPEN",
    };

    public ConfigLiteralPinTests() => Testing.ResetForTests();

    public void Dispose()
    {
        foreach (var v in Vars) Environment.SetEnvironmentVariable(v, null);
        Testing.ResetForTests();
    }

    private static void Set(string name, string? value) => Environment.SetEnvironmentVariable(name, value);

    [Fact]
    public void EveryEnvVarNameReachesExactlyItsField()
    {
        Set("PROVIDE_TELEMETRY_SERVICE_NAME", "svc-x");
        Set("PROVIDE_TELEMETRY_ENV", "env-x");
        Set("PROVIDE_TELEMETRY_VERSION", "9.9.9");
        Set("PROVIDE_TELEMETRY_STRICT_SCHEMA", "true");
        Set("PROVIDE_TELEMETRY_STRICT_EVENT_NAME", "true");
        Set("PROVIDE_TELEMETRY_REQUIRED_KEYS", " alpha ,, beta ");
        Set("PROVIDE_LOG_LEVEL", "DEBUG");
        Set("PROVIDE_LOG_FORMAT", "json");
        Set("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
        Set("PROVIDE_LOG_INCLUDE_CALLER", "false");
        Set("PROVIDE_LOG_SANITIZE", "false");
        Set("PROVIDE_LOG_PII_MAX_DEPTH", "7");
        Set("PROVIDE_LOG_OTLP_ENABLED", "false");
        Set("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://logs.example:4318");
        Set("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://traces.example:4318");
        Set("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://metrics.example:4318");
        Set("PROVIDE_TRACE_ENABLED", "false");
        Set("PROVIDE_TRACE_SAMPLE_RATE", "0.5");
        Set("PROVIDE_METRICS_ENABLED", "false");
        Set("PROVIDE_SAMPLING_LOGS_RATE", "0.25");
        Set("PROVIDE_SAMPLING_TRACES_RATE", "0.5");
        Set("PROVIDE_SAMPLING_METRICS_RATE", "0.75");
        Set("PROVIDE_EXPORTER_LOGS_RETRIES", "2");
        Set("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", "false");
        Set("PROVIDE_EXPORTER_TRACES_RETRIES", "3");
        Set("PROVIDE_EXPORTER_TRACES_FAIL_OPEN", "false");
        Set("PROVIDE_EXPORTER_METRICS_RETRIES", "4");
        Set("PROVIDE_EXPORTER_METRICS_FAIL_OPEN", "false");

        var cfg = ConfigEnv.ConfigFromEnv();

        Assert.Equal("svc-x", cfg.ServiceName);
        Assert.Equal("env-x", cfg.Environment);
        Assert.Equal("9.9.9", cfg.Version);
        Assert.True(cfg.StrictSchema);
        Assert.True(cfg.EventSchema.StrictEventName);
        Assert.Equal(new[] { "alpha", "beta" }, cfg.EventSchema.RequiredKeys);
        Assert.Equal("DEBUG", cfg.Logging.Level);
        Assert.Equal("json", cfg.Logging.Format);
        Assert.False(cfg.Logging.IncludeTimestamp);
        Assert.False(cfg.Logging.IncludeCaller);
        Assert.False(cfg.Logging.Sanitize);
        Assert.Equal(7, cfg.Logging.PiiMaxDepth);
        Assert.False(cfg.Logging.OtlpEnabled);
        Assert.Equal("http://logs.example:4318", cfg.Logging.OtlpEndpoint);
        Assert.Equal("http://traces.example:4318", cfg.Tracing.OtlpEndpoint);
        Assert.Equal("http://metrics.example:4318", cfg.Metrics.OtlpEndpoint);
        Assert.False(cfg.Tracing.Enabled);
        Assert.Equal(0.5, cfg.Tracing.SampleRate);
        Assert.False(cfg.Metrics.Enabled);
        Assert.Equal(0.25, cfg.Sampling.LogsRate);
        Assert.Equal(0.5, cfg.Sampling.TracesRate);
        Assert.Equal(0.75, cfg.Sampling.MetricsRate);
        Assert.Equal(2, cfg.Exporter.LogsRetries);
        Assert.False(cfg.Exporter.LogsFailOpen);
        Assert.Equal(3, cfg.Exporter.TracesRetries);
        Assert.False(cfg.Exporter.TracesFailOpen);
        Assert.Equal(4, cfg.Exporter.MetricsRetries);
        Assert.False(cfg.Exporter.MetricsFailOpen);
    }

    [Fact]
    public void TheSharedOtlpEndpointAndHeadersFanOutToAllThreeSignals()
    {
        Set("OTEL_EXPORTER_OTLP_ENDPOINT", "http://shared.example:4318");
        Set("OTEL_EXPORTER_OTLP_HEADERS", " api-key = secret%2Bplus , , =skipped ");

        var cfg = ConfigEnv.ConfigFromEnv();

        Assert.Equal("http://shared.example:4318", cfg.Logging.OtlpEndpoint);
        Assert.Equal("http://shared.example:4318", cfg.Tracing.OtlpEndpoint);
        Assert.Equal("http://shared.example:4318", cfg.Metrics.OtlpEndpoint);
        // %2B decodes to '+', names trim, the nameless pair is skipped.
        var header = Assert.Single(cfg.Logging.OtlpHeaders);
        Assert.Equal("api-key", header.Key);
        Assert.Equal("secret+plus", header.Value);
    }

    [Fact]
    public void ACleanEnvironmentYieldsEmptyEndpointsHeadersAndRequiredKeys()
    {
        var cfg = ConfigEnv.ConfigFromEnv();

        Assert.Equal("", cfg.Logging.OtlpEndpoint);
        Assert.Equal("", cfg.Tracing.OtlpEndpoint);
        Assert.Equal("", cfg.Metrics.OtlpEndpoint);
        Assert.Empty(cfg.Logging.OtlpHeaders);
        Assert.Empty(cfg.Tracing.OtlpHeaders);
        Assert.Empty(cfg.Metrics.OtlpHeaders);
        Assert.Empty(cfg.EventSchema.RequiredKeys);
    }

    [Theory]
    [InlineData("PROVIDE_TRACE_SAMPLE_RATE", "NaN")]
    [InlineData("PROVIDE_TRACE_SAMPLE_RATE", "Infinity")]
    [InlineData("PROVIDE_SAMPLING_LOGS_RATE", "-0.1")]
    [InlineData("PROVIDE_SAMPLING_TRACES_RATE", "2")]
    [InlineData("PROVIDE_SAMPLING_METRICS_RATE", "1.1")]
    public void EachInvalidRateShapeIsRejectedNamingTheField(string variable, string value)
    {
        Set(variable, value);

        var ex = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());

        Assert.Contains(variable, ex.Message);
        Assert.Contains("between 0 and 1", ex.Message);
    }

    [Fact]
    public void AZeroRateIsValidNotRejected()
    {
        Set("PROVIDE_TRACE_SAMPLE_RATE", "0");

        Assert.Equal(0.0, ConfigEnv.ConfigFromEnv().Tracing.SampleRate);
    }

    [Fact]
    public void NegativePiiDepthAndOversizedRetriesAreRejectedNamingFieldAndValue()
    {
        Set("PROVIDE_LOG_PII_MAX_DEPTH", "-1");
        var depth = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        Assert.Contains("PROVIDE_LOG_PII_MAX_DEPTH", depth.Message);
        Assert.Contains("-1", depth.Message);
        Set("PROVIDE_LOG_PII_MAX_DEPTH", null);

        Set("PROVIDE_EXPORTER_LOGS_RETRIES", "101");
        var retries = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        Assert.Contains("PROVIDE_EXPORTER_LOGS_RETRIES", retries.Message);
        Assert.Contains("at most 100", retries.Message);
        Set("PROVIDE_EXPORTER_LOGS_RETRIES", null);

        Set("PROVIDE_EXPORTER_TRACES_RETRIES", "-1");
        var negative = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
        Assert.Contains("PROVIDE_EXPORTER_TRACES_RETRIES", negative.Message);
        Assert.Contains("must not be negative, got -1", negative.Message);
    }

    [Fact]
    public void RedactConfigCarriesTheCanonicalKeysAndMasksByLength()
    {
        var cfg = TelemetryConfig.Default();
        cfg.ServiceName = "svc-r";
        cfg.Logging.OtlpEndpoint = "http://collector.example:4318";
        cfg.Logging.OtlpHeaders["k8"] = "12345678";
        cfg.Tracing.OtlpHeaders["k7"] = "1234567";

        var redacted = ConfigEnv.RedactConfig(cfg);

        Assert.Equal("svc-r", redacted["service_name"]);
        Assert.Equal("dev", redacted["environment"]);
        Assert.Equal("0.0.0", redacted["version"]);
        var logging = Assert.IsType<Dictionary<string, object?>>(redacted["logging"]);
        var tracing = Assert.IsType<Dictionary<string, object?>>(redacted["tracing"]);
        Assert.IsType<Dictionary<string, object?>>(redacted["metrics"]);
        // Exactly eight characters keeps a four-char prefix; seven does not.
        var loggingHeaders = Assert.IsType<Dictionary<string, string>>(logging["otlp_headers"]);
        Assert.Equal("1234****", loggingHeaders["k8"]);
        var tracingHeaders = Assert.IsType<Dictionary<string, string>>(tracing["otlp_headers"]);
        Assert.Equal("****", tracingHeaders["k7"]);
        Assert.NotNull(logging["otlp_endpoint"]);

        cfg.Metrics.OtlpEndpoint = "http://metrics.example:4318";
        cfg.Metrics.OtlpHeaders["k9"] = "abcdefgh";
        var remasked = ConfigEnv.RedactConfig(cfg);
        var metrics = Assert.IsType<Dictionary<string, object?>>(remasked["metrics"]);
        Assert.Equal("http://metrics.example:4318", metrics["otlp_endpoint"]);
        var metricsHeaders = Assert.IsType<Dictionary<string, string>>(metrics["otlp_headers"]);
        Assert.Equal("abcd****", metricsHeaders["k9"]);
    }

    [Fact]
    public void PercentDecodeLeavesTruncatedAndInvalidEscapesLiteral()
    {
        Assert.Equal("A", ConfigEnv.PercentDecode("%41"));
        Assert.Equal("x%4", ConfigEnv.PercentDecode("x%4"));
        Assert.Equal("x%", ConfigEnv.PercentDecode("x%"));
        Assert.Equal("%zz", ConfigEnv.PercentDecode("%zz"));
        Assert.Equal("a+b", ConfigEnv.PercentDecode("a+b"));
    }

    [Fact]
    public void EveryDtoDefaultHoldsItsDocumentedValue()
    {
        var logging = new LoggingConfig();
        Assert.Equal("INFO", logging.Level);
        Assert.Equal("console", logging.Format);
        Assert.Equal("", logging.OtlpEndpoint);

        var status = new RuntimeStatus();
        Assert.Equal("", status.SetupError);
        Assert.True(logging.IncludeTimestamp);
        Assert.True(logging.IncludeCaller);
        Assert.True(logging.Sanitize);

        var cfg = new TelemetryConfig();
        Assert.Equal("provide-service", cfg.ServiceName);
        Assert.Equal("dev", cfg.Environment);
        Assert.Equal("0.0.0", cfg.Version);
        Assert.False(cfg.StrictSchema);
        Assert.Equal("", cfg.Tracing.OtlpEndpoint);
        Assert.Equal("", cfg.Metrics.OtlpEndpoint);

        var policy = new ExporterPolicy();
        Assert.Equal(10.0, policy.TimeoutSeconds);
        Assert.True(policy.FailOpen);

        var snapshot = new HealthSnapshot();
        Assert.Equal("closed", snapshot.LogsCircuitState);
        Assert.Equal("closed", snapshot.TracesCircuitState);
        Assert.Equal("closed", snapshot.MetricsCircuitState);
        Assert.Equal("", snapshot.SetupError);

        var record = new EventRecord();
        Assert.Equal("", record.Event);
        Assert.Equal("", record.Domain);
        Assert.Equal("", record.Action);
        Assert.Equal("", record.Resource);
        Assert.Equal("", record.Status);

        var propagation = new PropagationContext();
        Assert.Equal("", propagation.Traceparent);
        Assert.Equal("", propagation.Tracestate);
        Assert.Equal("", propagation.Baggage);
        Assert.Equal("", propagation.TraceID);
        Assert.Equal("", propagation.SpanID);

        var receipt = new RedactionReceipt();
        Assert.Equal("", receipt.ReceiptId);
        Assert.Equal("", receipt.FieldPath);
        Assert.Equal("", receipt.Action);
        Assert.Equal("", receipt.ServiceName);
        Assert.Equal("", receipt.Timestamp);
        Assert.Equal("", receipt.OriginalHash);
        Assert.Equal("", receipt.Hmac);
    }

    [Fact]
    public void CloneCarriesBackpressureSloAndSecurityValues()
    {
        var cfg = TelemetryConfig.Default();
        cfg.Backpressure.LogsMaxSize = 11;
        cfg.Backpressure.TracesMaxSize = 12;
        cfg.Backpressure.MetricsMaxSize = 13;
        cfg.Slo.EnableRed = !cfg.Slo.EnableRed;
        cfg.Slo.EnableUse = !cfg.Slo.EnableUse;
        cfg.Security.EndpointValidation = !cfg.Security.EndpointValidation;

        var clone = cfg.Clone();

        Assert.Equal(11, clone.Backpressure.LogsMaxSize);
        Assert.Equal(12, clone.Backpressure.TracesMaxSize);
        Assert.Equal(13, clone.Backpressure.MetricsMaxSize);
        Assert.Equal(cfg.Slo.EnableRed, clone.Slo.EnableRed);
        Assert.Equal(cfg.Slo.EnableUse, clone.Slo.EnableUse);
        Assert.Equal(cfg.Security.EndpointValidation, clone.Security.EndpointValidation);
    }
}
