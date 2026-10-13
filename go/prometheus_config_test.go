// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// prometheus_config_test.go runs the config cases of spec/prometheus_fixtures.yaml
// (exporter_selection, listener_path, listener_port, translation_strategy)
// against ConfigFromEnv, plus the edges those cases do not pin.

package telemetry

import (
	"errors"
	"os"
	"slices"
	"strconv"
	"testing"

	"gopkg.in/yaml.v3"
)

type _promFixtures struct {
	ExporterSelection []struct {
		ID        string            `yaml:"id"`
		Env       map[string]string `yaml:"env"`
		Exporters []string          `yaml:"exporters"`
		Listener  bool              `yaml:"listener"`
		Warnings  []string          `yaml:"warnings"`
		Error     bool              `yaml:"error"`
	} `yaml:"exporter_selection"`
	ListenerPath []struct {
		ID    string  `yaml:"id"`
		Value *string `yaml:"value"`
		Path  string  `yaml:"path"`
		Error bool    `yaml:"error"`
	} `yaml:"listener_path"`
	ListenerPort []struct {
		ID    string  `yaml:"id"`
		Value *string `yaml:"value"`
		Port  int     `yaml:"port"`
		Error bool    `yaml:"error"`
	} `yaml:"listener_port"`
	TranslationStrategy []struct {
		ID       string  `yaml:"id"`
		Value    *string `yaml:"value"`
		Strategy string  `yaml:"strategy"`
		Error    bool    `yaml:"error"`
	} `yaml:"translation_strategy"`
}

func _loadPromFixtures(t *testing.T) _promFixtures {
	t.Helper()
	data, err := os.ReadFile("../spec/prometheus_fixtures.yaml")
	if err != nil {
		t.Fatalf("read fixtures: %v", err)
	}
	var f _promFixtures
	if err := yaml.Unmarshal(data, &f); err != nil {
		t.Fatalf("parse fixtures: %v", err)
	}
	return f
}

// _promEnvKeys are cleared before each case so ambient settings cannot leak in.
var _promEnvKeys = []string{ //nolint:gochecknoglobals
	"OTEL_METRICS_EXPORTER", "PROVIDE_METRICS_ENABLED", "PROVIDE_METRICS_PROMETHEUS_LISTEN",
	"OTEL_EXPORTER_PROMETHEUS_HOST", "OTEL_EXPORTER_PROMETHEUS_PORT", "PROVIDE_METRICS_PROMETHEUS_PATH",
	"PROVIDE_METRICS_PROMETHEUS_TRANSLATION", "PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS",
	"PROVIDE_METRICS_PROMETHEUS_TARGET_INFO", "PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG", "PROVIDE_METRICS_HEALTH_OTLP",
	"PROVIDE_TELEMETRY_STRICT_CONFIG",
}

func _promConfig(t *testing.T, env map[string]string) (*TelemetryConfig, error) {
	t.Helper()
	for _, k := range _promEnvKeys {
		t.Setenv(k, "")
	}
	for k, v := range env {
		t.Setenv(k, v)
	}
	return ConfigFromEnv()
}

func _wantConfigError(t *testing.T, id string, err error) {
	t.Helper()
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Fatalf("%s: want *ConfigurationError, got %v", id, err)
	}
}

func _selectedExporters(m MetricsConfig) []string {
	out := []string{}
	if m.OTLPReaderEnabled() {
		out = append(out, _metricsExporterOTLP)
	}
	if m.PrometheusReaderEnabled() {
		out = append(out, _metricsExporterPrometheus)
	}
	return out
}

func TestPrometheusFixtures_ExporterSelection(t *testing.T) {
	for _, c := range _loadPromFixtures(t).ExporterSelection {
		t.Run(c.ID, func(t *testing.T) {
			cfg, err := _promConfig(t, c.Env)
			if c.Error {
				_wantConfigError(t, c.ID, err)
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got := _selectedExporters(cfg.Metrics); !slices.Equal(got, c.Exporters) {
				t.Errorf("readers = %v, want %v", got, c.Exporters)
			}
			if got := cfg.Metrics.PrometheusListenerEnabled(); got != c.Listener {
				t.Errorf("listener = %v, want %v", got, c.Listener)
			}
			if got := cfg.Metrics.ExporterWarnings; !slices.Equal(got, c.Warnings) {
				t.Errorf("warnings = %q, want %q", got, c.Warnings)
			}
		})
	}
}

func TestPrometheusFixtures_ListenerPath(t *testing.T) {
	for _, c := range _loadPromFixtures(t).ListenerPath {
		t.Run(c.ID, func(t *testing.T) {
			env := map[string]string{}
			if c.Value != nil {
				env["PROVIDE_METRICS_PROMETHEUS_PATH"] = *c.Value
			}
			cfg, err := _promConfig(t, env)
			if c.Error {
				_wantConfigError(t, c.ID, err)
				return
			}
			if err != nil || cfg.Metrics.Prometheus.Path != c.Path {
				t.Fatalf("path = %v (err %v), want %q", cfg, err, c.Path)
			}
		})
	}
}

func TestPrometheusFixtures_ListenerPort(t *testing.T) {
	for _, c := range _loadPromFixtures(t).ListenerPort {
		t.Run(c.ID, func(t *testing.T) {
			env := map[string]string{}
			if c.Value != nil {
				env["OTEL_EXPORTER_PROMETHEUS_PORT"] = *c.Value
			}
			cfg, err := _promConfig(t, env)
			if c.Error {
				_wantConfigError(t, c.ID, err)
				return
			}
			if err != nil || cfg.Metrics.Prometheus.Port != c.Port {
				t.Fatalf("port = %v (err %v), want %d", cfg, err, c.Port)
			}
		})
	}
}

func TestPrometheusFixtures_TranslationStrategy(t *testing.T) {
	for _, c := range _loadPromFixtures(t).TranslationStrategy {
		t.Run(c.ID, func(t *testing.T) {
			env := map[string]string{}
			if c.Value != nil {
				env["PROVIDE_METRICS_PROMETHEUS_TRANSLATION"] = *c.Value
			}
			cfg, err := _promConfig(t, env)
			if c.Error {
				_wantConfigError(t, c.ID, err)
				return
			}
			if err != nil || cfg.Metrics.Prometheus.Translation != c.Strategy {
				t.Fatalf("translation = %v (err %v), want %q", cfg, err, c.Strategy)
			}
		})
	}
}

func TestPrometheusConfig_EveryNamedStrategyIsAccepted(t *testing.T) {
	for _, s := range PrometheusTranslationStrategies {
		cfg, err := _promConfig(t, map[string]string{"PROVIDE_METRICS_PROMETHEUS_TRANSLATION": s})
		if err != nil || cfg.Metrics.Prometheus.Translation != s {
			t.Fatalf("%s: got %v, err %v", s, cfg, err)
		}
	}
}

func TestPrometheusConfig_PortBoundaries(t *testing.T) {
	for _, port := range []int{0, 1, 65534, 65535} {
		cfg, err := _promConfig(t, map[string]string{"OTEL_EXPORTER_PROMETHEUS_PORT": strconv.Itoa(port)})
		if err != nil || cfg.Metrics.Prometheus.Port != port {
			t.Fatalf("port %d: got %v, err %v", port, cfg, err)
		}
	}
}

func TestPrometheusConfig_Defaults(t *testing.T) {
	cfg, err := _promConfig(t, nil)
	if err != nil {
		t.Fatal(err)
	}
	want := PrometheusConfig{
		Listen: "false", Host: "127.0.0.1", Port: 9464, Path: "/metrics",
		Translation: "UnderscoreEscapingWithSuffixes", ScopeLabels: false, TargetInfo: true, WebConfig: "",
	}
	if cfg.Metrics.Prometheus != want {
		t.Fatalf("defaults = %+v, want %+v", cfg.Metrics.Prometheus, want)
	}
	if !slices.Equal(cfg.Metrics.Exporters, []string{"otlp"}) || cfg.Metrics.HealthOTLP {
		t.Fatalf("exporters %v health %v", cfg.Metrics.Exporters, cfg.Metrics.HealthOTLP)
	}
}

func TestPrometheusConfig_ScalarSettingsAreRead(t *testing.T) {
	cfg, err := _promConfig(t, map[string]string{
		"OTEL_EXPORTER_PROMETHEUS_HOST":           " 0.0.0.0 ",
		"PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS": "true",
		"PROVIDE_METRICS_PROMETHEUS_TARGET_INFO":  "false",
		"PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG":   " /etc/web.yml ",
		"PROVIDE_METRICS_HEALTH_OTLP":             "true",
		"PROVIDE_METRICS_PROMETHEUS_LISTEN":       " TRUE ",
	})
	if err != nil {
		t.Fatal(err)
	}
	p := cfg.Metrics.Prometheus
	if p.Host != "0.0.0.0" || !p.ScopeLabels || p.TargetInfo || p.WebConfig != "/etc/web.yml" || p.Listen != "true" {
		t.Fatalf("got %+v", p)
	}
	if !cfg.Metrics.HealthOTLP {
		t.Fatal("PROVIDE_METRICS_HEALTH_OTLP not read")
	}
}

func TestPrometheusConfig_InvalidBoolsAreErrors(t *testing.T) {
	for _, key := range []string{
		"PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS", "PROVIDE_METRICS_PROMETHEUS_TARGET_INFO", "PROVIDE_METRICS_HEALTH_OTLP",
	} {
		_, err := _promConfig(t, map[string]string{key: "maybe"})
		_wantConfigError(t, key, err)
	}
}

func TestPrometheusConfig_ListenerDisabledWhenMetricsDisabled(t *testing.T) {
	m := MetricsConfig{Enabled: false, Exporters: []string{"prometheus", "otlp"}, Prometheus: PrometheusConfig{Listen: "true"}}
	if m.PrometheusListenerEnabled() || m.PrometheusReaderEnabled() || m.OTLPReaderEnabled() {
		t.Fatal("a disabled metrics signal must not enable any reader or the listener")
	}
}

func TestPrometheusConfig_UnknownListenValueStoredIsTreatedAsOff(t *testing.T) {
	m := MetricsConfig{Enabled: true, Exporters: []string{"prometheus"}, Prometheus: PrometheusConfig{Listen: "bogus"}}
	if m.PrometheusListenerEnabled() {
		t.Fatal("only true and auto may start the listener")
	}
}

func TestPrometheusConfig_BackendConfiguredByPrometheusAlone(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	if _backendConfigured(cfg) {
		t.Fatal("default config must not configure a backend")
	}
	cfg.Metrics.Exporters = []string{"prometheus"}
	if !_backendConfigured(cfg) {
		t.Fatal("a Prometheus reader needs the backend even without an OTLP endpoint")
	}
}

func TestPrometheusConfig_MeterFieldsChangedCoversNewFields(t *testing.T) {
	base := DefaultTelemetryConfig()
	mutations := map[string]func(*TelemetryConfig){
		"exporters":   func(c *TelemetryConfig) { c.Metrics.Exporters = []string{"prometheus"} },
		"health_otlp": func(c *TelemetryConfig) { c.Metrics.HealthOTLP = true },
		"prometheus":  func(c *TelemetryConfig) { c.Metrics.Prometheus.Port = 9100 },
	}
	if _meterFieldsChanged(base, cloneTelemetryConfig(base)) {
		t.Fatal("an identical config must not count as changed")
	}
	for name, mutate := range mutations {
		target := cloneTelemetryConfig(base)
		mutate(target)
		if !_meterFieldsChanged(base, target) {
			t.Errorf("%s change not detected", name)
		}
	}
}

func TestPrometheusConfig_CloneCopiesExporters(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Metrics.ExporterWarnings = []string{"w"}
	clone := cloneTelemetryConfig(cfg)
	clone.Metrics.Exporters[0] = "prometheus"
	clone.Metrics.ExporterWarnings[0] = "x"
	if cfg.Metrics.Exporters[0] != "otlp" {
		t.Fatal("clone shares the Exporters backing array with the original")
	}
	if cfg.Metrics.ExporterWarnings[0] != "w" {
		t.Fatal("clone shares the ExporterWarnings backing array with the original")
	}
}
