// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"crypto/tls"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func _envOf(m map[string]string) func(string) string {
	return func(k string) string { return m[k] }
}

func TestOTLPTLSConfig_NothingConfigured(t *testing.T) {
	if c, err := _otlpTLSConfig("METRICS", _envOf(nil)); c != nil || err != nil {
		t.Fatalf("got %v %v", c, err)
	}
}

func TestOTLPTLSConfig_CAAndClientPair(t *testing.T) {
	p := _newPKI(t)
	c, err := _otlpTLSConfig("TRACES", _envOf(map[string]string{
		"OTEL_EXPORTER_OTLP_CERTIFICATE":        p.caFile,
		"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE": p.clientCertFile,
		"OTEL_EXPORTER_OTLP_CLIENT_KEY":         p.clientKeyFile,
	}))
	if err != nil || c == nil || c.RootCAs == nil || len(c.Certificates) != 1 || c.MinVersion != tls.VersionTLS12 {
		t.Fatalf("got %+v %v", c, err)
	}
	if !c.RootCAs.Equal(p.pool) {
		t.Fatal("RootCAs is not the configured CA")
	}
}

func TestOTLPTLSConfig_ClientPairAloneAndCertWithoutKey(t *testing.T) {
	p := _newPKI(t)
	c, err := _otlpTLSConfig("LOGS", _envOf(map[string]string{
		"OTEL_EXPORTER_OTLP_LOGS_CLIENT_CERTIFICATE": p.clientCertFile,
		"OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY":         p.clientKeyFile,
	}))
	if err != nil || c == nil || c.RootCAs != nil || len(c.Certificates) != 1 {
		t.Fatalf("pair alone: %+v %v", c, err)
	}
	c, err = _otlpTLSConfig("LOGS", _envOf(map[string]string{"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE": p.clientCertFile}))
	if c != nil || err != nil {
		t.Fatalf("certificate without key: %+v %v", c, err)
	}
}

func TestOTLPTLSConfig_PerSignalWins(t *testing.T) {
	p := _newPKI(t)
	missing := filepath.Join(t.TempDir(), "missing.pem")
	c, err := _otlpTLSConfig("METRICS", _envOf(map[string]string{
		"OTEL_EXPORTER_OTLP_CERTIFICATE":         missing,
		"OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE": p.caFile,
	}))
	if err != nil || c == nil {
		t.Fatalf("per-signal good over shared bad: %+v %v", c, err)
	}
	_, err = _otlpTLSConfig("METRICS", _envOf(map[string]string{
		"OTEL_EXPORTER_OTLP_CERTIFICATE":         p.caFile,
		"OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE": missing,
	}))
	want := "OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE=" + missing + ": no such file or directory"
	if err == nil || err.Error() != want {
		t.Fatalf("got %v, want %q", err, want)
	}
	if _, err := _otlpTLSConfig("LOGS", _envOf(map[string]string{"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE": missing})); err != nil {
		t.Fatalf("another signal's file is not this one's: %v", err)
	}
}

func TestOTLPTLSConfig_Errors(t *testing.T) {
	p := _newPKI(t)
	dir := t.TempDir()
	missing := filepath.Join(dir, "missing.pem")
	garbage := filepath.Join(dir, "garbage.pem")
	if err := os.WriteFile(garbage, []byte("not pem"), 0o600); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		env  map[string]string
		want string
	}{
		{map[string]string{"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE": missing}, "OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE=" + missing + ": no such file or directory"},
		{map[string]string{"OTEL_EXPORTER_OTLP_CLIENT_KEY": missing}, "OTEL_EXPORTER_OTLP_CLIENT_KEY=" + missing + ": no such file or directory"},
		{map[string]string{"OTEL_EXPORTER_OTLP_CERTIFICATE": dir}, "OTEL_EXPORTER_OTLP_CERTIFICATE=" + dir + ": is a directory"},
		{map[string]string{"OTEL_EXPORTER_OTLP_CERTIFICATE": garbage}, "OTEL_EXPORTER_OTLP_CERTIFICATE=" + garbage + ": no PEM certificates"},
		{
			map[string]string{"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE": p.clientCertFile, "OTEL_EXPORTER_OTLP_CLIENT_KEY": p.keyFile},
			"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE=" + p.clientCertFile + ", OTEL_EXPORTER_OTLP_CLIENT_KEY=" + p.keyFile + ": tls: private key does not match public key",
		},
	}
	for _, c := range cases {
		cfg, err := _otlpTLSConfig("TRACES", _envOf(c.env))
		var tlsErr *_tlsFileError
		if cfg != nil || !errors.As(err, &tlsErr) || err.Error() != c.want {
			t.Errorf("%v: got %v %v, want %q", c.env, cfg, err, c.want)
		}
	}
}

func TestPathErrorReason_PassesOtherErrorsThrough(t *testing.T) {
	plain := errors.New("plain")
	if _pathErrorReason(plain) != plain {
		t.Fatal("a non-path error must come back unchanged")
	}
}

func TestOTLPTLSFor_NotesAndTakeClears(t *testing.T) {
	_takeTLSProblems()
	missing := filepath.Join(t.TempDir(), "missing.pem")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE", missing)
	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY", missing)
	if _, err := _otlpTLSFor("TRACES"); err == nil {
		t.Fatal("want an error")
	}
	if _, err := _otlpTLSFor("LOGS"); err == nil {
		t.Fatal("want an error")
	}
	if c, err := _otlpTLSFor("METRICS"); c != nil || err != nil {
		t.Fatalf("metrics: %v %v", c, err)
	}
	want := "OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE=" + missing + ": no such file or directory; " +
		"OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY=" + missing + ": no such file or directory"
	if got := _takeTLSProblems(); got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	if got := _takeTLSProblems(); got != "" {
		t.Fatalf("not cleared: %q", got)
	}
}

func TestOTLPTLS_BuildersSkipTheExporter(t *testing.T) {
	_takeTLSProblems()
	t.Cleanup(func() { _takeTLSProblems() })
	missing := filepath.Join(t.TempDir(), "missing.pem")
	t.Setenv("OTEL_EXPORTER_OTLP_CERTIFICATE", missing)
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Tracing.OTLPEndpoint = "https://127.0.0.1:1"
	cfg.Logging.OTLPEndpoint = "https://127.0.0.1:1"
	cfg.Metrics.OTLPEndpoint = "https://127.0.0.1:1"
	var tlsErr *_tlsFileError
	if tp, err := _buildDefaultTracerProvider(cfg); tp != nil || !errors.As(err, &tlsErr) {
		t.Fatalf("traces: %v %v", tp, err)
	}
	if lp, err := _buildLoggerProvider(cfg); lp != nil || !errors.As(err, &tlsErr) {
		t.Fatalf("logs: %v %v", lp, err)
	}
	if r, err := _newOTLPMetricsReader(cfg); r != nil || !errors.As(err, &tlsErr) {
		t.Fatalf("metrics reader: %v %v", r, err)
	}
	cfg.Metrics.Exporters = []string{"otlp", "prometheus"}
	mp, reg, err := _buildDefaultMeterProvider(cfg)
	if err != nil || mp == nil || reg == nil {
		t.Fatalf("the pull reader still serves: %v %v %v", mp, reg, err)
	}
	_ = mp.Shutdown(context.Background())
	if n := strings.Count(_takeTLSProblems(), "OTEL_EXPORTER_OTLP_CERTIFICATE="); n != 4 {
		t.Fatalf("%d problems noted, want 4", n)
	}
}

func TestOTLPTLS_MetricsBuildFailsForOtherErrors(t *testing.T) {
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Metrics.OTLPEndpoint = "http://[::1"
	cfg.Metrics.Exporters = []string{"otlp"}
	if mp, _, err := _buildDefaultMeterProvider(cfg); mp != nil || err == nil {
		t.Fatalf("bad endpoint: %v %v", mp, err)
	}
}

func TestOTLPTLS_ExporterGetsTheConfig(t *testing.T) {
	p := _newPKI(t)
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE", p.caFile)
	saved := _newOTLPMetricsExporter
	t.Cleanup(func() { _newOTLPMetricsExporter = saved })
	var got int
	_newOTLPMetricsExporter = func(ctx context.Context, opts ...otlpmetrichttp.Option) (sdkmetric.Exporter, error) {
		got = len(opts)
		return saved(ctx, opts...)
	}
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Metrics.OTLPEndpoint = "https://127.0.0.1:1"
	reader, err := _newOTLPMetricsReader(cfg)
	if err != nil || got != 3 {
		t.Fatalf("reader %v err %v, %d options (want endpoint, headers, TLS)", reader, err, got)
	}
	_ = reader.Shutdown(context.Background())
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE", "")
	reader, _ = _newOTLPMetricsReader(cfg)
	if got != 2 {
		t.Fatalf("%d options without TLS, want 2", got)
	}
	_ = reader.Shutdown(context.Background())
}

func TestOTLPTLS_SetupReportsTheProblem(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	missing := filepath.Join(t.TempDir(), "missing.pem")
	_tlsProblemsMu.Lock()
	_tlsProblems = append(_tlsProblems, "stale")
	_tlsProblemsMu.Unlock()
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "https://127.0.0.1:1/v1/metrics")
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE", missing)
	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("setup must not fail: %v", err)
	}
	want := "OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE=" + missing + ": no such file or directory"
	if got := telemetry.GetHealthSnapshot().SetupError; got != want {
		t.Fatalf("setup_error %q, want %q", got, want)
	}
	resetSetupState(t)
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE", "")
	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatal(err)
	}
	if got := telemetry.GetHealthSnapshot().SetupError; got != "" {
		t.Fatalf("setup_error %q after a clean setup", got)
	}
}

func TestOTLPTLS_IgnoredExporterWarningsComeFirst(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	missing := filepath.Join(t.TempDir(), "missing.pem")
	t.Setenv("OTEL_METRICS_EXPORTER", "otlp,statsd")
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "https://127.0.0.1:1/v1/metrics")
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE", missing)
	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("setup must not fail: %v", err)
	}
	want := "OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored; " +
		"OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE=" + missing + ": no such file or directory"
	if got := telemetry.GetHealthSnapshot().SetupError; got != want {
		t.Fatalf("setup_error %q, want %q", got, want)
	}
}

func TestBackend_IgnoredExporterWarningsSurviveACleanBackendSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus,console")
	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("setup must not fail: %v", err)
	}
	want := "OTEL_METRICS_EXPORTER: console is not supported by provide-telemetry, ignored"
	if got := telemetry.GetHealthSnapshot().SetupError; got != want {
		t.Fatalf("setup_error %q, want %q", got, want)
	}
}

func TestOTLPTLS_TraceAndLogExportersGetTheConfig(t *testing.T) {
	p := _newPKI(t)
	t.Setenv("OTEL_EXPORTER_OTLP_CERTIFICATE", p.caFile)
	savedTrace, savedLog := _newOTLPTraceExporter, _newOTLPLogExporter
	t.Cleanup(func() { _newOTLPTraceExporter, _newOTLPLogExporter = savedTrace, savedLog })
	var traceOpts, logOpts int
	_newOTLPTraceExporter = func(ctx context.Context, opts ...otlptracehttp.Option) (sdktrace.SpanExporter, error) {
		traceOpts = len(opts)
		return savedTrace(ctx, opts...)
	}
	_newOTLPLogExporter = func(ctx context.Context, opts ...otlploghttp.Option) (sdklog.Exporter, error) {
		logOpts = len(opts)
		return savedLog(ctx, opts...)
	}
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Tracing.OTLPEndpoint = "https://127.0.0.1:1"
	cfg.Logging.OTLPEndpoint = "https://127.0.0.1:1"
	tp, err := _buildDefaultTracerProvider(cfg)
	if err != nil || traceOpts != 3 {
		t.Fatalf("traces: %v, %d options", err, traceOpts)
	}
	_ = tp.Shutdown(context.Background())
	lp, err := _buildLoggerProvider(cfg)
	if err != nil || logOpts != 3 {
		t.Fatalf("logs: %v, %d options", err, logOpts)
	}
	_ = lp.Shutdown(context.Background())
}
