// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"math"
	"testing"
)

func TestReconfigureTelemetryAppliesHotFieldsWithoutProviders(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("first setup failed: %v", err)
	}

	// Change a hot field — should succeed (no OTel providers installed).
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.5")
	cfg2, err := ReconfigureTelemetry(context.Background())
	if err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}
	if cfg2 == nil {
		t.Fatal("expected non-nil config after reconfigure")
	}
	if cfg2.Sampling.LogsRate != 0.5 {
		t.Errorf("expected LogsRate=0.5, got %f", cfg2.Sampling.LogsRate)
	}
}

func TestReconfigureTelemetryRejectsProviderChangeWithProviders(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	RegisterBackend("fake", &_fakeBackend{})
	t.Cleanup(func() { UnregisterBackend("fake") })
	_setupMu.Lock()
	_activeBackend().(*_fakeBackend).providers = SignalStatus{Traces: true}
	_setupMu.Unlock()

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "changed-service")
	_, err = ReconfigureTelemetry(context.Background())
	if err == nil {
		t.Error("expected error when provider-changing field differs with providers installed")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected ConfigurationError, got: %T: %v", err, err)
	}
}

func TestReconfigureTelemetry_ReturnsConfigFromEnvError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "not-a-float")

	if _, err := ReconfigureTelemetry(context.Background()); err == nil {
		t.Fatal("expected config parse error during reconfigure")
	}
}

func TestReconfigureTelemetry_AppliesOptionIntentWithoutChangingRuntimeState(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	cfg, err := ReconfigureTelemetry(
		context.Background(),
		WithTracerProvider(struct{}{}),
		WithMeterProvider(struct{}{}),
		WithLoggerProvider(struct{}{}),
	)
	if err != nil {
		t.Fatalf("reconfigure with options failed: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config after reconfigure")
	}
}

func TestReconfigureTelemetry_RejectsBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_, err := ReconfigureTelemetry(context.Background())
	if err == nil {
		t.Error("expected error before setup")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected ConfigurationError, got: %T: %v", err, err)
	}
}

func TestReconfigureTelemetry_SucceedsWithHotFieldChangesOnly(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("SetupTelemetry failed: %v", err)
	}

	// No provider-changing env changes — should succeed.
	cfg, err := ReconfigureTelemetry(context.Background())
	if err != nil {
		t.Errorf("expected success with no provider changes, got: %v", err)
	}
	if cfg == nil {
		t.Error("expected non-nil config")
	}
}

func TestProviderConfigChanged_DetectsOTLPHeaderChanges(t *testing.T) {
	base := &TelemetryConfig{
		ServiceName: "svc",
		Tracing:     TracingConfig{OTLPHeaders: map[string]string{}},
		Metrics:     MetricsConfig{OTLPHeaders: map[string]string{}},
		Logging:     LoggingConfig{OTLPHeaders: map[string]string{}},
	}

	// Tracing header rotation must be detected when tracer is live.
	withTracingHeader := cloneTelemetryConfig(base)
	withTracingHeader.Tracing.OTLPHeaders["Authorization"] = "Bearer new"
	if !_providerConfigChanged(base, withTracingHeader, true, false, false) {
		t.Error("tracing header change must trigger provider-changed when tracer is live")
	}

	// Tracing header change must NOT trigger when tracer is NOT live.
	if _providerConfigChanged(base, withTracingHeader, false, false, false) {
		t.Error("tracing header change must not trigger provider-changed when no provider is live")
	}

	// Metrics header rotation must be detected when meter is live.
	withMetricsHeader := cloneTelemetryConfig(base)
	withMetricsHeader.Metrics.OTLPHeaders["Authorization"] = "Bearer new"
	if !_providerConfigChanged(base, withMetricsHeader, false, true, false) {
		t.Error("metrics header change must trigger provider-changed when meter is live")
	}

	// Metrics header change must NOT trigger when only tracer is live.
	if _providerConfigChanged(base, withMetricsHeader, true, false, false) {
		t.Error("metrics header change must not trigger when metrics provider is not live")
	}

	// Logging header rotation must be detected when logger is live.
	withLoggingHeader := cloneTelemetryConfig(base)
	withLoggingHeader.Logging.OTLPHeaders["Authorization"] = "Bearer new"
	if !_providerConfigChanged(base, withLoggingHeader, false, false, true) {
		t.Error("logging header change must trigger provider-changed when logger is live")
	}

	// Logging header change must NOT trigger when only tracer+meter are live.
	if _providerConfigChanged(base, withLoggingHeader, true, true, false) {
		t.Error("logging header change must not trigger when log provider is not live")
	}

	// Identical config must not trigger provider-changed regardless of which providers are live.
	same := cloneTelemetryConfig(base)
	if _providerConfigChanged(base, same, true, true, true) {
		t.Error("identical config must not trigger provider-changed")
	}

	// No providers live — must never trigger.
	if _providerConfigChanged(base, withTracingHeader, false, false, false) {
		t.Error("no live providers must never trigger provider-changed")
	}
}

func TestUpdateRuntimeConfigRejectsNaN(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	nanCases := []RuntimeOverrides{
		{Sampling: &SamplingConfig{LogsRate: math.NaN()}},
		{Exporter: &ExporterPolicyConfig{LogsTimeoutSeconds: math.Inf(1)}},
	}
	for _, overrides := range nanCases {
		if err := UpdateRuntimeConfig(overrides); err == nil {
			t.Fatalf("expected NaN/Inf override to be rejected: %+v", overrides)
		}
	}
}
