// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"github.com/prometheus/client_golang/prometheus"
	telemetry "github.com/provide-io/provide-telemetry/go"
)

// _healthCollector serves the health snapshot as provide_telemetry_* series on
// the pull path (prometheus_metrics.health_metrics in the spec). It reads the
// snapshot at scrape time and never goes through the MeterProvider, so OTLP
// never carries health about OTLP and the series stay visible while push is
// failing.
type _healthCollector struct {
	snapshot func() telemetry.HealthSnapshot
	signal   map[string]*prometheus.Desc
	global   map[string]*prometheus.Desc
}

type _signalHealth struct {
	name                                                            string
	emitted, dropped, failures, retries, blockingRisk, circuitOpens int64
	latencyMs                                                       float64
	circuitState                                                    string
}

const (
	_healthEmitted      = "provide_telemetry_emitted_total"
	_healthDropped      = "provide_telemetry_dropped_total"
	_healthFailures     = "provide_telemetry_export_failures_total"
	_healthRetries      = "provide_telemetry_export_retries_total"
	_healthLatency      = "provide_telemetry_export_latency_milliseconds"
	_healthBlockingRisk = "provide_telemetry_async_blocking_risk_total"
	_healthCircuit      = "provide_telemetry_circuit_state"
	_healthCircuitOpens = "provide_telemetry_circuit_open_total"
	_healthSetupError   = "provide_telemetry_setup_error"
	_healthReceipts     = "provide_telemetry_receipt_failures_total"
)

var _healthHelp = map[string]string{ //nolint:gochecknoglobals
	_healthEmitted:      "Records handed to the pipeline for this signal.",
	_healthDropped:      "Records refused before export (consent, sampling, or backpressure).",
	_healthFailures:     "Export attempts that returned an error or timed out.",
	_healthRetries:      "Retry attempts beyond the first.",
	_healthLatency:      "Latency of the most recent export.",
	_healthBlockingRisk: "Times a blocking export ran on an async event loop.",
	_healthCircuit:      "Export circuit breaker: 0 closed, 1 half-open, 2 open, -1 unknown.",
	_healthCircuitOpens: "Times the export circuit breaker has opened.",
	_healthSetupError:   "1 when the last setup failed, else 0.",
	_healthReceipts:     "Governance receipts a configured ReceiptSink refused or threw on.",
}

func _newHealthCollector(snapshot func() telemetry.HealthSnapshot) *_healthCollector {
	c := &_healthCollector{snapshot: snapshot, signal: map[string]*prometheus.Desc{}, global: map[string]*prometheus.Desc{}}
	for _, name := range []string{
		_healthEmitted, _healthDropped, _healthFailures, _healthRetries,
		_healthLatency, _healthBlockingRisk, _healthCircuit, _healthCircuitOpens,
	} {
		c.signal[name] = prometheus.NewDesc(name, _healthHelp[name], []string{"signal"}, nil)
	}
	for _, name := range []string{_healthSetupError, _healthReceipts} {
		c.global[name] = prometheus.NewDesc(name, _healthHelp[name], nil, nil)
	}
	return c
}

// Describe implements prometheus.Collector.
func (c *_healthCollector) Describe(ch chan<- *prometheus.Desc) {
	for _, d := range c.signal {
		ch <- d
	}
	for _, d := range c.global {
		ch <- d
	}
}

// Collect implements prometheus.Collector.
func (c *_healthCollector) Collect(ch chan<- prometheus.Metric) {
	s := c.snapshot()
	for _, sig := range _signalsOf(s) {
		c.collectSignal(ch, sig)
	}
	setupError := 0.0
	if s.SetupError != "" {
		setupError = 1
	}
	ch <- prometheus.MustNewConstMetric(c.global[_healthSetupError], prometheus.GaugeValue, setupError)
	ch <- prometheus.MustNewConstMetric(c.global[_healthReceipts], prometheus.CounterValue, float64(s.ReceiptFailures))
}

func (c *_healthCollector) collectSignal(ch chan<- prometheus.Metric, sig _signalHealth) {
	counters := map[string]int64{
		_healthEmitted: sig.emitted, _healthDropped: sig.dropped, _healthFailures: sig.failures,
		_healthRetries: sig.retries, _healthBlockingRisk: sig.blockingRisk, _healthCircuitOpens: sig.circuitOpens,
	}
	for name, v := range counters {
		ch <- prometheus.MustNewConstMetric(c.signal[name], prometheus.CounterValue, float64(v), sig.name)
	}
	ch <- prometheus.MustNewConstMetric(c.signal[_healthLatency], prometheus.GaugeValue, sig.latencyMs, sig.name)
	ch <- prometheus.MustNewConstMetric(c.signal[_healthCircuit], prometheus.GaugeValue, _circuitStateValue(sig.circuitState), sig.name)
}

func _signalsOf(s telemetry.HealthSnapshot) []_signalHealth {
	return []_signalHealth{
		{"logs", s.LogsEmitted, s.LogsDropped, s.LogsExportFailures, s.LogsRetries, s.LogsAsyncBlockingRisk, s.LogsCircuitOpenCount, s.LogsExportLatencyMs, s.LogsCircuitState},
		{"traces", s.TracesEmitted, s.TracesDropped, s.TracesExportFailures, s.TracesRetries, s.TracesAsyncBlockingRisk, s.TracesCircuitOpenCount, s.TracesExportLatencyMs, s.TracesCircuitState},
		{"metrics", s.MetricsEmitted, s.MetricsDropped, s.MetricsExportFailures, s.MetricsRetries, s.MetricsAsyncBlockingRisk, s.MetricsCircuitOpenCount, s.MetricsExportLatencyMs, s.MetricsCircuitState},
	}
}

// _circuitStateValue encodes a circuit state as prometheus_metrics.health_metrics
// specifies: closed 0, half-open 1, open 2, anything else -1.
func _circuitStateValue(state string) float64 {
	switch state {
	case "closed":
		return 0
	case "half-open":
		return 1
	case "open":
		return 2
	default:
		return -1
	}
}
