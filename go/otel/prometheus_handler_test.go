// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// prometheus_handler_test.go covers MetricsHandler and RenderPrometheus through
// real setup, one test per state in the handler_status cases of
// spec/prometheus_fixtures.yaml, plus the failure paths of the reader.

package otel

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"github.com/prometheus/client_golang/prometheus"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

func _promReset(t *testing.T) {
	t.Helper()
	resetSetupState(t)
	for _, k := range []string{
		"OTEL_METRICS_EXPORTER", "PROVIDE_METRICS_ENABLED", "PROVIDE_METRICS_PROMETHEUS_LISTEN",
		"PROVIDE_METRICS_PROMETHEUS_TRANSLATION",
	} {
		t.Setenv(k, "")
	}
	t.Cleanup(func() { resetSetupState(t) })
}

func _promSetup(t *testing.T, opts ...telemetry.SetupOption) {
	t.Helper()
	if _, err := telemetry.SetupTelemetry(opts...); err != nil {
		t.Fatalf("setup: %v", err)
	}
}

func _scrape(method string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	MetricsHandler().ServeHTTP(rec, httptest.NewRequest(method, "/metrics", nil))
	return rec
}

func _want503(t *testing.T, wantReason string) {
	t.Helper()
	rec := _scrape(http.MethodGet)
	if rec.Code != http.StatusServiceUnavailable || !strings.Contains(rec.Body.String(), wantReason) {
		t.Fatalf("got %d %q, want 503 containing %q", rec.Code, rec.Body.String(), wantReason)
	}
	if _, _, err := RenderPrometheus(); err == nil || !strings.Contains(err.Error(), wantReason) {
		t.Fatalf("RenderPrometheus error = %v, want one containing %q", err, wantReason)
	}
}

func TestMetricsHandler_BeforeSetup(t *testing.T) {
	_promReset(t)
	_want503(t, "not set up yet")
}

func TestMetricsHandler_ServesReaderAndHealth(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	_promSetup(t)
	telemetry.NewCounter("handler.probe.requests").Add(context.Background(), 2)

	rec := _scrape(http.MethodGet)
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "text/plain; version=0.0.4") {
		t.Fatalf("content type %q", ct)
	}
	body := rec.Body.String()
	for _, want := range []string{"handler_probe_requests_total", "provide_telemetry_emitted_total{signal=\"metrics\"}", "target_info"} {
		if !strings.Contains(body, want) {
			t.Errorf("body lacks %q:\n%s", want, body)
		}
	}
	if strings.Contains(body, "otel_scope_name") {
		t.Error("scope labels are off by default")
	}
	if head := _scrape(http.MethodHead); head.Code != http.StatusOK {
		t.Fatalf("HEAD status %d", head.Code)
	}

	rendered, ct, err := RenderPrometheus()
	if err != nil || !strings.Contains(string(rendered), "handler_probe_requests_total") || ct != rec.Header().Get("Content-Type") {
		t.Fatalf("RenderPrometheus = %q, %q, %v", rendered, ct, err)
	}
}

func TestMetricsHandler_ScopeLabelsAndTargetInfoSwitches(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	t.Setenv("PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS", "true")
	t.Setenv("PROVIDE_METRICS_PROMETHEUS_TARGET_INFO", "false")
	_promSetup(t)
	telemetry.NewCounter("switch.probe").Add(context.Background(), 1)
	body := _scrape(http.MethodGet).Body.String()
	if !strings.Contains(body, "otel_scope_name") || strings.Contains(body, "target_info") {
		t.Fatalf("switches not applied:\n%s", body)
	}
}

func TestMetricsHandler_RejectsOtherMethods(t *testing.T) {
	_promReset(t)
	rec := _scrape(http.MethodPost)
	if rec.Code != http.StatusMethodNotAllowed || rec.Header().Get("Allow") != "GET, HEAD" {
		t.Fatalf("got %d, Allow %q", rec.Code, rec.Header().Get("Allow"))
	}
}

func TestMetricsHandler_AfterShutdown(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	_promSetup(t)
	if err := telemetry.ShutdownTelemetry(context.Background()); err != nil {
		t.Fatal(err)
	}
	_want503(t, "shut down")
}

func TestMetricsHandler_MetricsDisabledWithoutBackend(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	t.Setenv("PROVIDE_METRICS_ENABLED", "false")
	_promSetup(t)
	_want503(t, "metrics are disabled")
}

func TestMetricsHandler_MetricsDisabledWithBackend(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	t.Setenv("PROVIDE_METRICS_ENABLED", "false")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://127.0.0.1:1/v1/traces")
	_promSetup(t)
	_want503(t, "metrics are disabled")
}

func TestMetricsHandler_NotSelectedWithoutBackend(t *testing.T) {
	_promReset(t)
	_promSetup(t)
	_want503(t, "not enabled")
}

func TestMetricsHandler_NotSelectedWithOTLPOnly(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://127.0.0.1:1/v1/metrics")
	_promSetup(t)
	_want503(t, "not enabled")
}

func TestMetricsHandler_HostOwnedProvider(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	mp := sdkmetric.NewMeterProvider()
	t.Cleanup(func() { _ = mp.Shutdown(context.Background()) })
	_promSetup(t, telemetry.WithMeterProvider(mp))
	_want503(t, "host application owns")
}

func TestMetricsHandler_ProviderBuildFailure(t *testing.T) {
	_promReset(t)
	t.Setenv("OTEL_METRICS_EXPORTER", "otlp,prometheus")
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://127.0.0.1:1/v1/metrics")
	_newOTLPMetricsExporter = func(context.Context, ...otlpmetrichttp.Option) (sdkmetric.Exporter, error) {
		return nil, errors.New("exporter refused")
	}
	_promSetup(t)
	_want503(t, "failed to start")
}

// _failingRegistry fails the Register call numbered failOn (1-based).
type _failingRegistry struct {
	*prometheus.Registry
	calls, failOn int
}

func (r *_failingRegistry) Register(c prometheus.Collector) error {
	r.calls++
	if r.calls == r.failOn {
		return errors.New("register refused")
	}
	return r.Registry.Register(c)
}

func TestPrometheusReader_RegistrationFailuresSurface(t *testing.T) {
	saved := _newPromRegistry
	t.Cleanup(func() { _newPromRegistry = saved })
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Metrics.Exporters = []string{"prometheus"}
	for _, failOn := range []int{1, 2} { // 1: the exporter's collector, 2: the health collector
		_newPromRegistry = func() _promRegistryLike {
			return &_failingRegistry{Registry: prometheus.NewRegistry(), failOn: failOn}
		}
		if reader, reg, err := _newPrometheusReader(cfg); err == nil || reader != nil || reg != nil {
			t.Fatalf("failOn %d: got %v %v %v, want an error and nothing else", failOn, reader, reg, err)
		}
		if mp, reg, err := _buildDefaultMeterProvider(cfg); err == nil || mp != nil || reg != nil {
			t.Fatalf("failOn %d: provider build should fail, got %v %v %v", failOn, mp, reg, err)
		}
	}
}
