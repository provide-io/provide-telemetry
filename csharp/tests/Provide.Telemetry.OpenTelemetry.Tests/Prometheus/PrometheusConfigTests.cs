// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>The Prometheus config keys: the shared fixture cases plus the edges around them.</summary>
[Collection("OpenTelemetry")]
public sealed class PrometheusConfigTests
{
    public static IEnumerable<object[]> ExporterSelection() => PromFixtures.Rows("exporter_selection");

    private static List<string> Readers(MetricsConfig m)
    {
        var readers = new List<string>();
        if (m.OtlpReaderEnabled()) readers.Add("otlp");
        if (m.PrometheusReaderEnabled()) readers.Add("prometheus");
        return readers;
    }

    [Theory]
    [MemberData(nameof(ExporterSelection))]
    public void ExporterSelection_FixtureCase(string id, Dictionary<object, object?> c)
    {
        using var env = EnvScope.From(c.Map("env"));
        if (c.Flag("error"))
        {
            Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
            return;
        }
        var metrics = ConfigEnv.ConfigFromEnv().Metrics;
        Assert.True(c.Strings("exporters").SequenceEqual(Readers(metrics)), id);
        Assert.Equal(c.Flag("listener"), metrics.PrometheusListenerEnabled());
    }

    public static IEnumerable<object[]> SingleSettings()
    {
        foreach (var (section, key) in new[]
                 {
                     ("listener_path", "PROVIDE_METRICS_PROMETHEUS_PATH"),
                     ("listener_port", "OTEL_EXPORTER_PROMETHEUS_PORT"),
                     ("translation_strategy", "PROVIDE_METRICS_PROMETHEUS_TRANSLATION"),
                 })
        {
            foreach (var row in PromFixtures.Rows(section)) yield return [section, key, row[0], row[1]];
        }
    }

    [Theory]
    [MemberData(nameof(SingleSettings))]
    public void SingleSetting_FixtureCase(string section, string key, string id, Dictionary<object, object?> c)
    {
        using var env = new EnvScope();
        if (c["value"] is string value) env.Set(key, value);
        if (c.Flag("error"))
        {
            var error = Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv());
            Assert.StartsWith(key + ": ", error.Message);
            return;
        }
        var p = ConfigEnv.ConfigFromEnv().Metrics.Prometheus;
        object actual = section switch
        {
            "listener_path" => p.Path,
            "listener_port" => p.Port.ToString(System.Globalization.CultureInfo.InvariantCulture),
            _ => p.Translation,
        };
        var want = c.Str("path") ?? c.Str("port") ?? c.Str("strategy");
        Assert.True(Equals(want, actual), $"{section}/{id}: want {want}, got {actual}");
    }

    [Fact]
    public void Defaults_MatchTheSpec()
    {
        using var env = new EnvScope();
        var m = ConfigEnv.ConfigFromEnv().Metrics;
        Assert.Equal(["otlp"], m.Exporters);
        Assert.False(m.HealthOtlp);
        Assert.Equal("false", m.Prometheus.Listen);
        Assert.Equal("127.0.0.1", m.Prometheus.Host);
        Assert.Equal(9464, m.Prometheus.Port);
        Assert.Equal("/metrics", m.Prometheus.Path);
        Assert.Equal("UnderscoreEscapingWithSuffixes", m.Prometheus.Translation);
        Assert.False(m.Prometheus.ScopeLabels);
        Assert.True(m.Prometheus.TargetInfo);
        Assert.Equal("", m.Prometheus.WebConfig);
    }

    [Fact]
    public void EveryKey_IsReadAndTrimmed()
    {
        using var env = new EnvScope(new Dictionary<string, string?>
        {
            ["PROVIDE_METRICS_HEALTH_OTLP"] = "true",
            ["PROVIDE_METRICS_PROMETHEUS_LISTEN"] = " auto ",
            ["OTEL_EXPORTER_PROMETHEUS_HOST"] = " 0.0.0.0 ",
            ["OTEL_EXPORTER_PROMETHEUS_PORT"] = " 9100 ",
            ["PROVIDE_METRICS_PROMETHEUS_PATH"] = " /m ",
            ["PROVIDE_METRICS_PROMETHEUS_TRANSLATION"] = " NoTranslation ",
            ["PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS"] = "true",
            ["PROVIDE_METRICS_PROMETHEUS_TARGET_INFO"] = "false",
            ["PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG"] = " /etc/web.yml ",
        });
        var m = ConfigEnv.ConfigFromEnv().Metrics;
        Assert.True(m.HealthOtlp);
        Assert.Equal("auto", m.Prometheus.Listen);
        Assert.Equal("0.0.0.0", m.Prometheus.Host);
        Assert.Equal(9100, m.Prometheus.Port);
        Assert.Equal("/m", m.Prometheus.Path);
        Assert.Equal("NoTranslation", m.Prometheus.Translation);
        Assert.True(m.Prometheus.ScopeLabels);
        Assert.False(m.Prometheus.TargetInfo);
        Assert.Equal("/etc/web.yml", m.Prometheus.WebConfig);
    }

    [Theory]
    [InlineData("PROVIDE_METRICS_PROMETHEUS_LISTEN", "   ", "false")]
    [InlineData("OTEL_EXPORTER_PROMETHEUS_HOST", "  ", "127.0.0.1")]
    public void BlankValues_MeanTheDefault(string key, string raw, string want)
    {
        using var env = new EnvScope(new Dictionary<string, string?> { [key] = raw });
        var p = ConfigEnv.ConfigFromEnv().Metrics.Prometheus;
        Assert.Equal(want, key.EndsWith("LISTEN", StringComparison.Ordinal) ? p.Listen : p.Host);
    }

    [Theory]
    [InlineData("otlp,statsd", "OTEL_METRICS_EXPORTER: unknown exporter 'statsd'")]
    [InlineData("none,otlp", "OTEL_METRICS_EXPORTER: none cannot be combined with other exporters")]
    public void BadExporters_NameTheProblem(string raw, string message)
    {
        using var env = new EnvScope(new Dictionary<string, string?> { ["OTEL_METRICS_EXPORTER"] = raw });
        Assert.Equal(message, Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv()).Message);
    }

    [Theory]
    [InlineData("PROVIDE_METRICS_PROMETHEUS_LISTEN", "yes",
        "PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got 'yes'")]
    [InlineData("OTEL_EXPORTER_PROMETHEUS_PORT", "http",
        "OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got 'http'")]
    [InlineData("OTEL_EXPORTER_PROMETHEUS_PORT", "65536",
        "OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got 65536")]
    [InlineData("OTEL_EXPORTER_PROMETHEUS_PORT", "1e3",
        "OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got '1e3'")]
    [InlineData("PROVIDE_METRICS_PROMETHEUS_PATH", "/a?b",
        "PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got '/a?b'")]
    [InlineData("PROVIDE_METRICS_PROMETHEUS_TRANSLATION", "Legacy",
        "PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy 'Legacy'")]
    public void BadValues_NameTheVariableAndValue(string key, string raw, string message)
    {
        using var env = new EnvScope(new Dictionary<string, string?> { [key] = raw });
        Assert.Equal(message, Assert.Throws<ConfigurationError>(() => ConfigEnv.ConfigFromEnv()).Message);
    }

    [Theory]
    [InlineData(-1)]
    [InlineData(65536)]
    public void Validate_RejectsAPortOutOfRange(int port)
    {
        var m = new MetricsConfig { Prometheus = new PrometheusConfig { Port = port } };
        Assert.Throws<ConfigurationError>(() => PrometheusSettings.Validate(m));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(65535)]
    public void Validate_AcceptsThePortBounds(int port) =>
        PrometheusSettings.Validate(new MetricsConfig { Prometheus = new PrometheusConfig { Port = port } });

    [Fact]
    public void Validate_RejectsCodeBuiltValuesTheParserWouldRefuse()
    {
        Assert.Equal("metrics exporters: unknown 'none'", Assert.Throws<ConfigurationError>(
            () => PrometheusSettings.Validate(new MetricsConfig { Exporters = ["none"] })).Message);
        Assert.Throws<ConfigurationError>(() => PrometheusSettings.Validate(
            new MetricsConfig { Prometheus = new PrometheusConfig { Path = "/a#b" } }));
        Assert.Throws<ConfigurationError>(() => PrometheusSettings.Validate(
            new MetricsConfig { Prometheus = new PrometheusConfig { Path = "metrics" } }));
        Assert.Throws<ArgumentNullException>(() => PrometheusSettings.Validate(null!));
    }

    [Fact]
    public void Validate_AcceptsEveryStrategy()
    {
        foreach (var strategy in new[]
                 {
                     "UnderscoreEscapingWithSuffixes", "UnderscoreEscapingWithoutSuffixes",
                     "NoUTF8EscapingWithSuffixes", "NoTranslation",
                 })
        {
            PrometheusSettings.Validate(new MetricsConfig { Prometheus = new PrometheusConfig { Translation = strategy } });
        }
    }

    [Fact]
    public void Validate_AcceptsBothExporters() =>
        PrometheusSettings.Validate(new MetricsConfig { Exporters = ["otlp", "prometheus"] });

    [Fact]
    public void ParseExporters_NullIsTheDefault() =>
        Assert.Equal(["otlp"], PrometheusSettings.ParseExporters(null));

    [Fact]
    public void ParsePort_NullIsTheDefault() => Assert.Equal(9464, PrometheusSettings.ParsePort(null));

    [Fact]
    public void Listener_IsOffWhenMetricsAreDisabledWhateverListenSays()
    {
        var m = new MetricsConfig { Enabled = false, Exporters = ["prometheus"] };
        m.Prometheus.Listen = "true";
        Assert.False(m.PrometheusListenerEnabled());
        Assert.False(m.PrometheusReaderEnabled());
        Assert.False(m.OtlpReaderEnabled());
        m.Enabled = true;
        Assert.True(m.PrometheusListenerEnabled());
        m.Prometheus.Listen = "auto";
        m.Exporters = ["otlp"];
        Assert.False(m.PrometheusListenerEnabled());
        Assert.False(m.PrometheusReaderEnabled());
    }

    [Fact]
    public void Clone_CopiesThePrometheusSettingsDeeply()
    {
        var cfg = new TelemetryConfig();
        cfg.Metrics.Exporters = ["prometheus"];
        cfg.Metrics.HealthOtlp = true;
        cfg.Metrics.Prometheus.Path = "/x";
        cfg.Metrics.OtlpCertificate = "ca";
        cfg.Metrics.OtlpClientCertificate = "cert";
        cfg.Metrics.OtlpClientKey = "key";
        cfg.Logging.OtlpCertificate = "lca";
        cfg.Logging.OtlpClientCertificate = "lcert";
        cfg.Logging.OtlpClientKey = "lkey";
        cfg.Tracing.OtlpCertificate = "tca";
        cfg.Tracing.OtlpClientCertificate = "tcert";
        cfg.Tracing.OtlpClientKey = "tkey";
        var copy = cfg.Clone();
        cfg.Metrics.Exporters.Add("otlp");
        cfg.Metrics.Prometheus.Path = "/y";
        Assert.Equal(["prometheus"], copy.Metrics.Exporters);
        Assert.True(copy.Metrics.HealthOtlp);
        Assert.Equal("/x", copy.Metrics.Prometheus.Path);
        Assert.Equal(("ca", "cert", "key"),
            (copy.Metrics.OtlpCertificate, copy.Metrics.OtlpClientCertificate, copy.Metrics.OtlpClientKey));
        Assert.Equal(("lca", "lcert", "lkey"),
            (copy.Logging.OtlpCertificate, copy.Logging.OtlpClientCertificate, copy.Logging.OtlpClientKey));
        Assert.Equal(("tca", "tcert", "tkey"),
            (copy.Tracing.OtlpCertificate, copy.Tracing.OtlpClientCertificate, copy.Tracing.OtlpClientKey));
    }

    // ── push security: per-signal headers and TLS files ──────────────────────

    [Fact]
    public void PerSignalHeaders_ReplaceTheSharedOnes()
    {
        using var env = new EnvScope(new Dictionary<string, string?>
        {
            ["OTEL_EXPORTER_OTLP_HEADERS"] = "a=shared,b=shared",
            ["OTEL_EXPORTER_OTLP_METRICS_HEADERS"] = "Authorization=Basic%20xyz",
            ["OTEL_EXPORTER_OTLP_TRACES_HEADERS"] = "t=1",
        });
        var cfg = ConfigEnv.ConfigFromEnv();
        Assert.Equal(new Dictionary<string, string> { ["Authorization"] = "Basic xyz" }, cfg.Metrics.OtlpHeaders);
        Assert.Equal(new Dictionary<string, string> { ["t"] = "1" }, cfg.Tracing.OtlpHeaders);
        Assert.Equal(new Dictionary<string, string> { ["a"] = "shared", ["b"] = "shared" }, cfg.Logging.OtlpHeaders);
        cfg.Logging.OtlpHeaders["c"] = "x";
        Assert.False(ConfigEnv.ConfigFromEnv().Tracing.OtlpHeaders.ContainsKey("c"));
    }

    [Fact]
    public void LogsHeaders_AreReadToo()
    {
        using var env = new EnvScope(new Dictionary<string, string?> { ["OTEL_EXPORTER_OTLP_LOGS_HEADERS"] = "l=1" });
        var cfg = ConfigEnv.ConfigFromEnv();
        Assert.Equal("1", cfg.Logging.OtlpHeaders["l"]);
        Assert.Empty(cfg.Metrics.OtlpHeaders);
    }

    [Theory]
    [InlineData("LOGS")]
    [InlineData("TRACES")]
    [InlineData("METRICS")]
    public void TlsFiles_PerSignalWins(string signal)
    {
        using var env = new EnvScope(new Dictionary<string, string?>
        {
            ["OTEL_EXPORTER_OTLP_CERTIFICATE"] = "shared-ca",
            ["OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE"] = "shared-cert",
            ["OTEL_EXPORTER_OTLP_CLIENT_KEY"] = "shared-key",
            [$"OTEL_EXPORTER_OTLP_{signal}_CERTIFICATE"] = "own-ca",
            [$"OTEL_EXPORTER_OTLP_{signal}_CLIENT_CERTIFICATE"] = "own-cert",
            [$"OTEL_EXPORTER_OTLP_{signal}_CLIENT_KEY"] = "own-key",
        });
        var cfg = ConfigEnv.ConfigFromEnv();
        var all = new[]
        {
            ("LOGS", (cfg.Logging.OtlpCertificate, cfg.Logging.OtlpClientCertificate, cfg.Logging.OtlpClientKey)),
            ("TRACES", (cfg.Tracing.OtlpCertificate, cfg.Tracing.OtlpClientCertificate, cfg.Tracing.OtlpClientKey)),
            ("METRICS", (cfg.Metrics.OtlpCertificate, cfg.Metrics.OtlpClientCertificate, cfg.Metrics.OtlpClientKey)),
        };
        foreach (var (name, files) in all)
        {
            Assert.Equal(name == signal ? ("own-ca", "own-cert", "own-key") : ("shared-ca", "shared-cert", "shared-key"), files);
        }
    }
}
