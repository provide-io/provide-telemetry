// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"

	"github.com/prometheus/client_golang/prometheus"
	dto "github.com/prometheus/client_model/go"
	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
	otelmetric "go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/metric/noop"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
)

func _healthSnapshotFixture() telemetry.HealthSnapshot {
	return telemetry.HealthSnapshot{
		LogsEmitted: 1, TracesEmitted: 2, MetricsEmitted: 3,
		LogsDropped: 4, LogsExportFailures: 5, LogsRetries: 6, LogsExportLatencyMs: 7.5,
		LogsAsyncBlockingRisk: 8, LogsCircuitState: _circuitOpenState, LogsCircuitOpenCount: 9,
		TracesCircuitState: _circuitHalfOpen, MetricsCircuitState: _circuitClosed,
		SetupError: "boom", ReceiptFailures: 10,
	}
}

// _collectHealth registers the health instruments on a fresh provider and
// returns name -> "signal" attribute ("" for globals) -> value, and kinds.
func _collectHealth(t *testing.T, snapshot telemetry.HealthSnapshot) (map[string]map[string]float64, map[string]string) {
	t.Helper()
	reader := sdkmetric.NewManualReader()
	provider := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	if err := _registerHealthInstruments(provider.Meter("provide.telemetry"), func() telemetry.HealthSnapshot { return snapshot }); err != nil {
		t.Fatalf("register: %v", err)
	}
	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatalf("collect: %v", err)
	}
	values, kinds := map[string]map[string]float64{}, map[string]string{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			values[m.Name] = map[string]float64{}
			switch data := m.Data.(type) {
			case metricdata.Sum[float64]:
				kinds[m.Name] = "counter"
				if !data.IsMonotonic || data.Temporality != metricdata.CumulativeTemporality {
					t.Fatalf("%s: monotonic %v temporality %v", m.Name, data.IsMonotonic, data.Temporality)
				}
				for _, p := range data.DataPoints {
					sig, _ := p.Attributes.Value(attribute.Key("signal"))
					values[m.Name][sig.AsString()] = p.Value
				}
			case metricdata.Gauge[float64]:
				kinds[m.Name] = "gauge"
				for _, p := range data.DataPoints {
					sig, _ := p.Attributes.Value(attribute.Key("signal"))
					values[m.Name][sig.AsString()] = p.Value
				}
			default:
				t.Fatalf("%s: unexpected data %T", m.Name, m.Data)
			}
			if m.Unit != "" || m.Description != "" {
				t.Fatalf("%s: unit %q description %q, want none", m.Name, m.Unit, m.Description)
			}
		}
	}
	return values, kinds
}

func TestHealthOTLP_InstrumentsCarryTheSnapshot(t *testing.T) {
	values, kinds := _collectHealth(t, _healthSnapshotFixture())
	if len(values) != 10 {
		t.Fatalf("got %d instruments, want 10: %v", len(values), kinds)
	}
	wantKinds := map[string]string{
		_healthEmitted: "counter", _healthDropped: "counter", _healthFailures: "counter", _healthRetries: "counter",
		_healthLatency: "gauge", _healthBlockingRisk: "counter", _healthCircuit: "gauge", _healthCircuitOpens: "counter",
		_healthSetupError: "gauge", _healthReceipts: "counter",
	}
	for name, kind := range wantKinds {
		if kinds[name] != kind {
			t.Errorf("%s: kind %q, want %q", name, kinds[name], kind)
		}
	}
	checks := []struct {
		name, signal string
		want         float64
	}{
		{_healthEmitted, _signalLogs, 1}, {_healthEmitted, _signalTraces, 2}, {_healthEmitted, _signalMetrics, 3},
		{_healthDropped, _signalLogs, 4}, {_healthFailures, _signalLogs, 5}, {_healthRetries, _signalLogs, 6},
		{_healthLatency, _signalLogs, 7.5}, {_healthBlockingRisk, _signalLogs, 8}, {_healthCircuitOpens, _signalLogs, 9},
		{_healthCircuit, _signalLogs, 2}, {_healthCircuit, _signalTraces, 1}, {_healthCircuit, _signalMetrics, 0},
		{_healthSetupError, "", 1}, {_healthReceipts, "", 10},
	}
	for _, c := range checks {
		if got, ok := values[c.name][c.signal]; !ok || got != c.want {
			t.Errorf("%s{signal=%q} = %v (present %v), want %v", c.name, c.signal, got, ok, c.want)
		}
	}
	for name, series := range values {
		want := 3
		if name == _healthSetupError || name == _healthReceipts {
			want = 1
		}
		if len(series) != want {
			t.Errorf("%s: %d series, want %d", name, len(series), want)
		}
	}
}

func TestHealthOTLP_SetupErrorZeroAndUnknownCircuit(t *testing.T) {
	snapshot := _healthSnapshotFixture()
	snapshot.SetupError = ""
	snapshot.LogsCircuitState = "weird"
	values, _ := _collectHealth(t, snapshot)
	if values[_healthSetupError][""] != 0 || values[_healthCircuit][_signalLogs] != -1 {
		t.Fatalf("setup_error %v circuit %v", values[_healthSetupError], values[_healthCircuit])
	}
}

type _failingMeter struct {
	noop.Meter
	failGauge, failCounter, failCallback bool
}

func (m _failingMeter) Float64ObservableGauge(name string, o ...otelmetric.Float64ObservableGaugeOption) (otelmetric.Float64ObservableGauge, error) {
	if m.failGauge {
		return nil, errors.New("gauge refused")
	}
	return m.Meter.Float64ObservableGauge(name, o...)
}

func (m _failingMeter) Float64ObservableCounter(name string, o ...otelmetric.Float64ObservableCounterOption) (otelmetric.Float64ObservableCounter, error) {
	if m.failCounter {
		return nil, errors.New("counter refused")
	}
	return m.Meter.Float64ObservableCounter(name, o...)
}

func (m _failingMeter) RegisterCallback(f otelmetric.Callback, i ...otelmetric.Observable) (otelmetric.Registration, error) {
	if m.failCallback {
		return nil, errors.New("callback refused")
	}
	return m.Meter.RegisterCallback(f, i...)
}

func TestHealthOTLP_RegistrationErrorsSurface(t *testing.T) {
	snapshot := func() telemetry.HealthSnapshot { return telemetry.HealthSnapshot{} }
	for _, m := range []_failingMeter{{failGauge: true}, {failCounter: true}, {failCallback: true}} {
		if err := _registerHealthInstruments(m, snapshot); err == nil {
			t.Fatalf("%+v: want an error", m)
		}
	}
	if err := _registerHealthInstruments(_failingMeter{}, snapshot); err != nil {
		t.Fatalf("noop meter: %v", err)
	}
}

func TestHealthOTLP_ProviderBuild(t *testing.T) {
	saved := _registerHealth
	t.Cleanup(func() { _registerHealth = saved })
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Metrics.Exporters = []string{"prometheus"}
	calls := 0
	_registerHealth = func(otelmetric.Meter, func() telemetry.HealthSnapshot) error { calls++; return nil }
	if _, _, err := _buildDefaultMeterProvider(cfg); err != nil || calls != 0 {
		t.Fatalf("health_otlp off: err %v, %d registrations", err, calls)
	}
	cfg.Metrics.HealthOTLP = true
	if mp, _, err := _buildDefaultMeterProvider(cfg); err != nil || mp == nil || calls != 1 {
		t.Fatalf("health_otlp on: %v %v, %d registrations", mp, err, calls)
	}
	_registerHealth = func(otelmetric.Meter, func() telemetry.HealthSnapshot) error { return errors.New("refused") }
	if mp, reg, err := _buildDefaultMeterProvider(cfg); err == nil || mp != nil || reg != nil {
		t.Fatalf("failed registration: %v %v %v", mp, reg, err)
	}
}

func TestHealthOTLP_ScrapeServesEachHealthFamilyOnce(t *testing.T) {
	for _, on := range []string{"true", "false"} {
		t.Run(on, func(t *testing.T) {
			_promReset(t)
			t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
			t.Setenv("PROVIDE_METRICS_HEALTH_OTLP", on)
			_promSetup(t)
			rec := _scrape(http.MethodGet)
			body := rec.Body.String()
			if rec.Code != http.StatusOK {
				t.Fatalf("status %d: %s", rec.Code, body)
			}
			for name := range _healthHelp {
				if n := strings.Count(body, "# TYPE "+name+" "); n != 1 {
					t.Errorf("%s: %d TYPE lines, want 1\n%s", name, n, body)
				}
			}
			if !strings.Contains(body, "# HELP "+_healthEmitted+" "+_healthHelp[_healthEmitted]) {
				t.Errorf("want the collector's copy (with help text):\n%s", body)
			}
		})
	}
}

type _stubGatherer struct {
	families []*dto.MetricFamily
	err      error
}

func (g _stubGatherer) Gather() ([]*dto.MetricFamily, error) { return g.families, g.err }

func TestWithoutHealth_FiltersAndKeepsTheError(t *testing.T) {
	name := func(s string) *dto.MetricFamily { return &dto.MetricFamily{Name: &s} }
	wantErr := errors.New("partial")
	got, err := _withoutHealth{_stubGatherer{[]*dto.MetricFamily{name("app_total"), name(_healthEmitted), name("x")}, wantErr}}.Gather()
	if !errors.Is(err, wantErr) || len(got) != 2 || got[0].GetName() != "app_total" || got[1].GetName() != "x" {
		t.Fatalf("got %v %v", got, err)
	}
	var _ prometheus.Gatherer = _servedRegistry{}
}
