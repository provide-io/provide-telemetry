// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"bytes"
	"errors"
	"net/http"
	"strings"
	"sync"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	dto "github.com/prometheus/client_model/go"
	"github.com/prometheus/otlptranslator"
	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
	promexporter "go.opentelemetry.io/otel/exporters/prometheus"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

// _promStatus says why the Prometheus endpoint can or cannot serve. Every
// non-ready status maps to a 503 whose body names the reason: an empty 200
// would read as "this process has no metrics" rather than "not wired".
type _promStatus int

const (
	_promNotSetUp _promStatus = iota
	_promReady
	_promShutDown
	_promMetricsDisabled
	_promHostProvider
	_promNotSelected
	_promSetupFailed
)

var _promStatusReasons = map[_promStatus]string{ //nolint:gochecknoglobals
	_promNotSetUp:        "provide-telemetry: metrics are not set up yet",
	_promShutDown:        "provide-telemetry: telemetry has been shut down",
	_promMetricsDisabled: "provide-telemetry: metrics are disabled (PROVIDE_METRICS_ENABLED=false)",
	_promHostProvider:    "provide-telemetry: the host application owns the MeterProvider; serve its registry instead",
	_promNotSelected:     "provide-telemetry: the Prometheus reader is not enabled (add prometheus to OTEL_METRICS_EXPORTER)",
	_promSetupFailed:     "provide-telemetry: the metrics provider failed to start; see the otel.meter_provider_init_failed log",
}

// _promRegistryLike is what the reader registers into and the handler serves.
type _promRegistryLike interface {
	prometheus.Registerer
	prometheus.Gatherer
}

var (
	_promMu       sync.RWMutex      //nolint:gochecknoglobals
	_promState    = _promNotSetUp   //nolint:gochecknoglobals
	_promRegistry _promRegistryLike //nolint:gochecknoglobals

	// _newPromRegistry is a seam so tests can make registration fail; in
	// production every setup gets a fresh private registry.
	_newPromRegistry = func() _promRegistryLike { return prometheus.NewRegistry() } //nolint:gochecknoglobals
)

// _setPromState records the endpoint status and, when ready, the registry it serves.
func _setPromState(status _promStatus, registry _promRegistryLike) {
	_promMu.Lock()
	defer _promMu.Unlock()
	_promState = status
	_promRegistry = registry
}

// _currentProm returns the registry to serve, or nil and the reason there is none.
func _currentProm() (_promRegistryLike, string) {
	_promMu.RLock()
	status, registry := _promState, _promRegistry
	_promMu.RUnlock()
	if status == _promReady {
		return registry, ""
	}
	return nil, _promStatusReasons[_refineNotSetUp(status)]
}

// _refineNotSetUp turns "not set up" into the real reason when setup did run but
// never reached this backend's meter setup, which happens when no signal needed
// the backend: metrics disabled, or nothing selected the Prometheus reader.
func _refineNotSetUp(status _promStatus) _promStatus {
	if status != _promNotSetUp {
		return status
	}
	rs := telemetry.GetRuntimeStatus()
	switch {
	case !rs.SetupDone:
		return _promNotSetUp
	case !rs.Signals.Metrics:
		return _promMetricsDisabled
	default:
		return _promNotSelected
	}
}

// _newPrometheusReader builds the pull reader for cfg on a fresh private
// registry, so a host already using prometheus.DefaultRegisterer cannot collide
// with it, and the health collector on a second one. A scrape gathers both,
// minus any health-named family from the reader: with PROVIDE_METRICS_HEALTH_OTLP
// the provider carries the health instruments too, and the scrape serves only
// the collector's copy.
func _newPrometheusReader(cfg *telemetry.TelemetryConfig) (sdkmetric.Reader, _promRegistryLike, error) {
	registry := _newPromRegistry()
	reader, err := promexporter.New(_prometheusExporterOptions(cfg.Metrics.Prometheus, registry)...)
	if err != nil {
		return nil, nil, err
	}
	health := _newPromRegistry()
	if err := health.Register(_newHealthCollector(telemetry.GetHealthSnapshot)); err != nil {
		return nil, nil, err
	}
	return reader, _servedRegistry{Registerer: registry, Gatherer: prometheus.Gatherers{_withoutHealth{registry}, health}}, nil
}

// _servedRegistry is what a scrape gathers: the reader's registry, filtered,
// and the health collector's.
type _servedRegistry struct {
	prometheus.Registerer
	prometheus.Gatherer
}

// _withoutHealth drops the health-named families from a gather.
type _withoutHealth struct{ prometheus.Gatherer }

func (g _withoutHealth) Gather() ([]*dto.MetricFamily, error) {
	families, err := g.Gatherer.Gather()
	kept := make([]*dto.MetricFamily, 0, len(families))
	for _, f := range families {
		if _, health := _healthHelp[f.GetName()]; !health {
			kept = append(kept, f)
		}
	}
	return kept, err
}

func _prometheusExporterOptions(p telemetry.PrometheusConfig, registry prometheus.Registerer) []promexporter.Option {
	opts := []promexporter.Option{
		promexporter.WithRegisterer(registry),
		promexporter.WithTranslationStrategy(otlptranslator.TranslationStrategyOption(p.Translation)),
	}
	if !p.ScopeLabels {
		opts = append(opts, promexporter.WithoutScopeInfo())
	}
	if !p.TargetInfo {
		opts = append(opts, promexporter.WithoutTargetInfo())
	}
	return opts
}

// MetricsHandler returns the Tier 2 pull handler: mount it on the host's own
// HTTP server at whatever path the host chooses. It serves GET and HEAD only.
// Until setup has installed a provide-telemetry MeterProvider with the
// Prometheus reader (OTEL_METRICS_EXPORTER=prometheus), and after shutdown, it
// answers 503 with a one-line reason.
func MetricsHandler() http.Handler {
	return http.HandlerFunc(_serveMetrics)
}

func _serveMetrics(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	registry, reason := _currentProm()
	if registry == nil {
		http.Error(w, reason, http.StatusServiceUnavailable)
		return
	}
	promhttp.HandlerFor(registry, promhttp.HandlerOpts{ErrorHandling: promhttp.ContinueOnError}).ServeHTTP(w, r)
}

// RenderPrometheus runs one collection and returns it in the Prometheus text
// format with its content type, for hosts whose server MetricsHandler does not
// fit. It goes through the same handler, so the output is byte-for-byte what a
// plain scrape would get. When there is nothing to serve it returns an error
// naming the reason.
func RenderPrometheus() ([]byte, string, error) {
	resp := &_bufferedResponse{header: http.Header{}, status: http.StatusOK}
	_serveMetrics(resp, &http.Request{Method: http.MethodGet, Header: http.Header{}})
	if resp.status != http.StatusOK {
		return nil, "", errors.New(strings.TrimSpace(resp.body.String()))
	}
	return resp.body.Bytes(), resp.header.Get("Content-Type"), nil
}

// _bufferedResponse is the minimal http.ResponseWriter RenderPrometheus needs.
type _bufferedResponse struct {
	header http.Header
	status int
	body   bytes.Buffer
}

func (r *_bufferedResponse) Header() http.Header         { return r.header }
func (r *_bufferedResponse) Write(b []byte) (int, error) { return r.body.Write(b) }
func (r *_bufferedResponse) WriteHeader(status int)      { r.status = status }

// _prometheusLabelView drops attributes the Prometheus output cannot carry:
// keys the reference translator rejects, and keys it translates to a label
// name starting with "__", which Prometheus reserves. client_golang would
// otherwise reject the whole metric at scrape time. Views apply to every
// reader, so these keys are also dropped from OTLP while the Prometheus reader
// is attached (prometheus_metrics.translation.rules).
func _prometheusLabelView(p telemetry.PrometheusConfig) sdkmetric.View {
	namer := otlptranslator.LabelNamer{UTF8Allowed: !otlptranslator.TranslationStrategyOption(p.Translation).ShouldEscape()}
	filter := func(kv attribute.KeyValue) bool {
		name, err := namer.Build(string(kv.Key))
		return err == nil && !strings.HasPrefix(name, "__")
	}
	return sdkmetric.NewView(sdkmetric.Instrument{Name: "*"}, sdkmetric.Stream{AttributeFilter: filter})
}
