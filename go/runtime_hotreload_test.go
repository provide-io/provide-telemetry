// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"
)

func TestUpdateRuntimeConfigUpdatesField(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling: &SamplingConfig{LogsRate: 0.5, TracesRate: 1.0, MetricsRate: 1.0},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.Sampling.LogsRate != 0.5 {
		t.Errorf("expected Sampling.LogsRate=0.5, got %v", cfg.Sampling.LogsRate)
	}
}

func TestUpdateRuntimeConfigReappliesRuntimePolicies(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling:     &SamplingConfig{LogsRate: 0.25, TracesRate: 1.0, MetricsRate: 1.0},
		Backpressure: &BackpressureConfig{LogsMaxSize: 17},
		Exporter: &ExporterPolicyConfig{
			LogsRetries:        2,
			LogsBackoffSeconds: 1.5,
			LogsTimeoutSeconds: 22,
			LogsFailOpen:       false,
		},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if p, err := GetSamplingPolicy(signalLogs); err != nil {
		t.Fatal(err)
	} else if p.DefaultRate != 0.25 {
		t.Fatalf("sampling policy not updated, got %v", p.DefaultRate)
	}
	if got := GetQueuePolicy().LogsMaxSize; got != 17 {
		t.Fatalf("queue policy not updated, got %d", got)
	}
	exporter := GetExporterPolicy(signalLogs)
	if exporter.Retries != 2 || exporter.BackoffSeconds != 1.5 || exporter.TimeoutSeconds != 22 || exporter.FailOpen {
		t.Fatalf("exporter policy not updated, got %+v", exporter)
	}
}

func TestUpdateRuntimeConfigErrorWhenNotSetUp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling: &SamplingConfig{LogsRate: 0.5, TracesRate: 1.0, MetricsRate: 1.0},
	})
	if err == nil {
		t.Error("expected error when calling UpdateRuntimeConfig without setup")
	}
}

func TestRuntimeOverridesAppliesHotFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	depth := 12
	strict := true
	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling:     &SamplingConfig{LogsRate: 0.1, TracesRate: 0.2, MetricsRate: 0.3},
		Backpressure: &BackpressureConfig{LogsMaxSize: 100, TracesMaxSize: 200, MetricsMaxSize: 300},
		Security:     &SecurityConfig{MaxAttrValueLength: 512, MaxAttrCount: 32, MaxNestingDepth: 4},
		SLO:          &SLOConfig{EnableREDMetrics: true, EnableUSEMetrics: true, IncludeErrorTaxonomy: false},
		PIIMaxDepth:  &depth,
		StrictSchema: &strict,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.Sampling.LogsRate != 0.1 || cfg.Sampling.TracesRate != 0.2 || cfg.Sampling.MetricsRate != 0.3 {
		t.Fatalf("sampling not applied: %+v", cfg.Sampling)
	}
	if cfg.Backpressure.LogsMaxSize != 100 || cfg.Backpressure.TracesMaxSize != 200 || cfg.Backpressure.MetricsMaxSize != 300 {
		t.Fatalf("backpressure not applied: %+v", cfg.Backpressure)
	}
	if cfg.Security.MaxAttrValueLength != 512 || cfg.Security.MaxAttrCount != 32 || cfg.Security.MaxNestingDepth != 4 {
		t.Fatalf("security not applied: %+v", cfg.Security)
	}
	if !cfg.SLO.EnableREDMetrics || !cfg.SLO.EnableUSEMetrics || cfg.SLO.IncludeErrorTaxonomy {
		t.Fatalf("SLO not applied: %+v", cfg.SLO)
	}
	if cfg.Logging.PIIMaxDepth != 12 {
		t.Fatalf("PIIMaxDepth not applied: got %d", cfg.Logging.PIIMaxDepth)
	}
	if !cfg.StrictSchema {
		t.Fatal("StrictSchema not applied")
	}
}

func TestUpdateRuntimeConfigRejectsInvalidOverrides(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	invalid := []RuntimeOverrides{
		{Sampling: &SamplingConfig{LogsRate: -0.1}},
		{Sampling: &SamplingConfig{LogsRate: 1.1}},
		{Sampling: &SamplingConfig{LogsRate: 0.5, TracesRate: -0.1}},
		{Sampling: &SamplingConfig{LogsRate: 0.5, TracesRate: 0.5, MetricsRate: 1.1}},
		{Backpressure: &BackpressureConfig{LogsMaxSize: -1}},
		{Backpressure: &BackpressureConfig{LogsMaxSize: 1, TracesMaxSize: -1}},
		{Backpressure: &BackpressureConfig{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: -1}},
		{Exporter: &ExporterPolicyConfig{LogsRetries: -1}},
		{Exporter: &ExporterPolicyConfig{TracesRetries: -1}},
		{Exporter: &ExporterPolicyConfig{MetricsRetries: -1}},
		{Exporter: &ExporterPolicyConfig{LogsBackoffSeconds: -1}},
		{Exporter: &ExporterPolicyConfig{TracesBackoffSeconds: -1}},
		{Exporter: &ExporterPolicyConfig{MetricsBackoffSeconds: -1}},
		{Exporter: &ExporterPolicyConfig{LogsTimeoutSeconds: -1}},
		{Exporter: &ExporterPolicyConfig{TracesTimeoutSeconds: -1}},
		{Exporter: &ExporterPolicyConfig{MetricsTimeoutSeconds: -1}},
		{Security: &SecurityConfig{MaxAttrValueLength: -1}},
		{Security: &SecurityConfig{MaxAttrValueLength: 1, MaxAttrCount: -1}},
		{Security: &SecurityConfig{MaxAttrValueLength: 1, MaxAttrCount: 1, MaxNestingDepth: -1}},
		{PIIMaxDepth: ptrInt(-1)},
	}

	for _, overrides := range invalid {
		if err := UpdateRuntimeConfig(overrides); err == nil {
			t.Fatalf("expected invalid overrides to be rejected: %+v", overrides)
		}
	}
}
