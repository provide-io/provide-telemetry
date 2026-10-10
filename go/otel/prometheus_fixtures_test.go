// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// prometheus_fixtures_test.go runs the metric_names, label_names and
// health_metrics cases of spec/prometheus_fixtures.yaml against the Prometheus
// reader and the health collector.

package otel

import (
	"context"
	"fmt"
	"os"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/prometheus/client_golang/prometheus"
	dto "github.com/prometheus/client_model/go"
	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
	otelmetric "go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"gopkg.in/yaml.v3"
)

type _promNameCase struct {
	ID         string            `yaml:"id"`
	Name       string            `yaml:"name"`
	Unit       string            `yaml:"unit"`
	Instrument string            `yaml:"instrument"`
	Expected   map[string]string `yaml:"expected"`
}

type _promLabelCase struct {
	Attribute string `yaml:"attribute"`
	Escaped   string `yaml:"escaped"`
	UTF8      string `yaml:"utf8"`
}

type _promSample struct {
	Metric string            `yaml:"metric"`
	Labels map[string]string `yaml:"labels"`
	Value  float64           `yaml:"value"`
}

type _promHealthCase struct {
	ID                string                 `yaml:"id"`
	Snapshot          map[string]interface{} `yaml:"snapshot"`
	SnapshotOverrides map[string]interface{} `yaml:"snapshot_overrides"`
	ExpectedSamples   []_promSample          `yaml:"expected_samples"`
}

type _promOtelFixtures struct {
	MetricNames   []_promNameCase   `yaml:"metric_names"`
	LabelNames    []_promLabelCase  `yaml:"label_names"`
	HealthMetrics []_promHealthCase `yaml:"health_metrics"`
}

func _loadPromOtelFixtures(t *testing.T) _promOtelFixtures {
	t.Helper()
	data, err := os.ReadFile("../../spec/prometheus_fixtures.yaml")
	if err != nil {
		t.Fatalf("read fixtures: %v", err)
	}
	var f _promOtelFixtures
	if err := yaml.Unmarshal(data, &f); err != nil {
		t.Fatalf("parse fixtures: %v", err)
	}
	return f
}

// _promTestProvider builds a MeterProvider whose only reader is the
// Prometheus reader configured with strategy.
func _promTestProvider(t *testing.T, strategy string) (*sdkmetric.MeterProvider, _promRegistryLike) {
	t.Helper()
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Metrics.Exporters = []string{"prometheus"}
	cfg.Metrics.Prometheus.Translation = strategy
	reader, registry, err := _newPrometheusReader(cfg)
	if err != nil {
		t.Fatalf("new reader: %v", err)
	}
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	t.Cleanup(func() { _ = mp.Shutdown(context.Background()) })
	return mp, registry
}

// _recordInstrument creates the named instrument kind and records one value.
func _recordInstrument(t *testing.T, meter otelmetric.Meter, kind, name, unit string, attrs ...attribute.KeyValue) {
	t.Helper()
	ctx := context.Background()
	set := otelmetric.WithAttributes(attrs...)
	var err error
	switch kind {
	case "counter":
		var c otelmetric.Int64Counter
		if c, err = meter.Int64Counter(name, otelmetric.WithUnit(unit)); err == nil {
			c.Add(ctx, 1, set)
		}
	case "gauge":
		var g otelmetric.Float64Gauge
		if g, err = meter.Float64Gauge(name, otelmetric.WithUnit(unit)); err == nil {
			g.Record(ctx, 1, set)
		}
	case "histogram":
		var h otelmetric.Float64Histogram
		if h, err = meter.Float64Histogram(name, otelmetric.WithUnit(unit)); err == nil {
			h.Record(ctx, 1, set)
		}
	case "observable_counter":
		_, err = meter.Int64ObservableCounter(name, otelmetric.WithUnit(unit),
			otelmetric.WithInt64Callback(func(_ context.Context, o otelmetric.Int64Observer) error { o.Observe(1, set); return nil }))
	case "observable_gauge":
		_, err = meter.Float64ObservableGauge(name, otelmetric.WithUnit(unit),
			otelmetric.WithFloat64Callback(func(_ context.Context, o otelmetric.Float64Observer) error { o.Observe(1, set); return nil }))
	case "observable_up_down_counter":
		_, err = meter.Float64ObservableUpDownCounter(name, otelmetric.WithUnit(unit),
			otelmetric.WithFloat64Callback(func(_ context.Context, o otelmetric.Float64Observer) error { o.Observe(1, set); return nil }))
	default:
		t.Fatalf("fixture names unknown instrument %q", kind)
	}
	if err != nil {
		t.Fatalf("create %s %q: %v", kind, name, err)
	}
}

func _nonHealthFamilies(t *testing.T, registry _promRegistryLike) []*dto.MetricFamily {
	t.Helper()
	families, err := registry.Gather()
	if err != nil {
		t.Fatalf("gather: %v", err)
	}
	out := []*dto.MetricFamily{}
	for _, f := range families {
		if !strings.HasPrefix(f.GetName(), "provide_telemetry_") && f.GetName() != "target_info" {
			out = append(out, f)
		}
	}
	return out
}

func TestPrometheusFixtures_MetricNames(t *testing.T) {
	for _, c := range _loadPromOtelFixtures(t).MetricNames {
		for strategy, want := range c.Expected {
			t.Run(c.ID+"/"+strategy, func(t *testing.T) {
				mp, registry := _promTestProvider(t, strategy)
				_recordInstrument(t, mp.Meter("fixture"), c.Instrument, c.Name, c.Unit)
				families := _nonHealthFamilies(t, registry)
				if len(families) != 1 || families[0].GetName() != want {
					names := []string{}
					for _, f := range families {
						names = append(names, f.GetName())
					}
					t.Fatalf("families = %v, want [%s]", names, want)
				}
			})
		}
	}
}

func TestPrometheusFixtures_LabelNames(t *testing.T) {
	cases := _loadPromOtelFixtures(t).LabelNames
	for _, strategy := range telemetry.PrometheusTranslationStrategies {
		t.Run(strategy, func(t *testing.T) {
			mp, registry := _promTestProvider(t, strategy)
			attrs := []attribute.KeyValue{}
			for _, c := range cases {
				attrs = append(attrs, attribute.String(c.Attribute, "v"))
			}
			_recordInstrument(t, mp.Meter("fixture"), "counter", "labels.probe", "", attrs...)
			got := map[string]bool{}
			for _, l := range _nonHealthFamilies(t, registry)[0].GetMetric()[0].GetLabel() {
				got[l.GetName()] = true
			}
			escaping := strings.HasPrefix(strategy, "UnderscoreEscaping")
			for _, c := range cases {
				want := c.UTF8
				if escaping {
					want = c.Escaped
				}
				if !got[want] {
					t.Errorf("attribute %q: label %q missing from %v", c.Attribute, want, got)
				}
			}
		})
	}
}

// _snapshotFromFixture maps fixture keys such as export_latency_ms_traces onto
// HealthSnapshot fields such as TracesExportLatencyMs.
func _snapshotFromFixture(t *testing.T, values map[string]interface{}) telemetry.HealthSnapshot {
	t.Helper()
	var s telemetry.HealthSnapshot
	v := reflect.ValueOf(&s).Elem()
	for key, raw := range values {
		field := v.FieldByName(_snapshotFieldName(key))
		if !field.IsValid() {
			t.Fatalf("fixture key %q has no HealthSnapshot field %q", key, _snapshotFieldName(key))
		}
		switch field.Kind() {
		case reflect.String:
			field.SetString(fmt.Sprint(raw))
		case reflect.Int64:
			field.SetInt(int64(raw.(int)))
		default:
			field.SetFloat(reflect.ValueOf(raw).Convert(reflect.TypeOf(0.0)).Float())
		}
	}
	return s
}

func _snapshotFieldName(key string) string {
	parts := strings.Split(key, "_")
	last := parts[len(parts)-1]
	if last == "logs" || last == "traces" || last == "metrics" {
		parts = append([]string{last}, parts[:len(parts)-1]...)
	}
	for i, p := range parts {
		parts[i] = strings.ToUpper(p[:1]) + p[1:]
	}
	return strings.Join(parts, "")
}

func _samplesFrom(t *testing.T, registry *prometheus.Registry) map[string]float64 {
	t.Helper()
	families, err := registry.Gather()
	if err != nil {
		t.Fatalf("gather: %v", err)
	}
	out := map[string]float64{}
	for _, f := range families {
		for _, m := range f.GetMetric() {
			value := m.GetGauge().GetValue()
			if m.GetCounter() != nil {
				value = m.GetCounter().GetValue()
			}
			out[_sampleKey(f.GetName(), m.GetLabel())] = value
		}
	}
	return out
}

func _sampleKey(name string, labels []*dto.LabelPair) string {
	pairs := []string{}
	for _, l := range labels {
		pairs = append(pairs, l.GetName()+"="+l.GetValue())
	}
	sort.Strings(pairs)
	return name + "{" + strings.Join(pairs, ",") + "}"
}

func TestPrometheusFixtures_HealthMetrics(t *testing.T) {
	cases := _loadPromOtelFixtures(t).HealthMetrics
	full := cases[0].Snapshot
	for _, c := range cases {
		t.Run(c.ID, func(t *testing.T) {
			values := map[string]interface{}{}
			for k, v := range full {
				values[k] = v
			}
			for k, v := range c.SnapshotOverrides {
				values[k] = v
			}
			snapshot := _snapshotFromFixture(t, values)
			registry := prometheus.NewRegistry()
			registry.MustRegister(_newHealthCollector(func() telemetry.HealthSnapshot { return snapshot }))
			got := _samplesFrom(t, registry)
			for _, want := range c.ExpectedSamples {
				pairs := []*dto.LabelPair{}
				for k, v := range want.Labels {
					pairs = append(pairs, &dto.LabelPair{Name: &k, Value: &v})
				}
				key := _sampleKey(want.Metric, pairs)
				if value, ok := got[key]; !ok || value != want.Value {
					t.Errorf("%s = %v (present %v), want %v", key, value, ok, want.Value)
				}
			}
			if c.ID == "full_snapshot" && len(got) != len(c.ExpectedSamples) {
				t.Errorf("collector emitted %d series, fixture lists %d", len(got), len(c.ExpectedSamples))
			}
		})
	}
}

func TestPrometheusHealth_UnknownCircuitStateIsMinusOne(t *testing.T) {
	for state, want := range map[string]float64{"closed": 0, "half-open": 1, "open": 2, "": -1, "weird": -1} {
		if got := _circuitStateValue(state); got != want {
			t.Errorf("%q -> %v, want %v", state, got, want)
		}
	}
}
