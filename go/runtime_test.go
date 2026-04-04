// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"testing"
)

func TestGetRuntimeConfigNilBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if cfg := GetRuntimeConfig(); cfg != nil {
		t.Errorf("expected nil before setup, got %+v", cfg)
	}
}

func TestGetRuntimeConfigNonNilAfterSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if cfg := GetRuntimeConfig(); cfg == nil {
		t.Error("expected non-nil config after setup")
	}
}

func TestUpdateRuntimeConfigUpdatesField(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := UpdateRuntimeConfig(func(cfg *TelemetryConfig) {
		cfg.ServiceName = "updated-service"
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.ServiceName != "updated-service" {
		t.Errorf("expected ServiceName=%q, got %q", "updated-service", cfg.ServiceName)
	}
}

func TestUpdateRuntimeConfigErrorWhenNotSetUp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	err := UpdateRuntimeConfig(func(cfg *TelemetryConfig) {
		cfg.ServiceName = "should-not-apply"
	})
	if err == nil {
		t.Error("expected error when calling UpdateRuntimeConfig without setup")
	}
}

func TestReloadRuntimeFromEnvUpdatesConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "reloaded-service")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config after reload")
	}
	if cfg.ServiceName != "reloaded-service" {
		t.Errorf("expected ServiceName=%q after reload, got %q", "reloaded-service", cfg.ServiceName)
	}
}

func TestReloadRuntimeFromEnvErrorWhenNotSetUp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if err := ReloadRuntimeFromEnv(); err == nil {
		t.Error("expected error when reloading without setup")
	}
}

func TestReloadRuntimeFromEnvConfigFromEnvError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	// Inject an invalid env var so that ConfigFromEnv fails on reload.
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "not-a-float")

	if err := ReloadRuntimeFromEnv(); err == nil {
		t.Error("expected error from ReloadRuntimeFromEnv with invalid env var")
	}
}

func TestReconfigureTelemetryRerunsSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg1, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("first setup failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "reconfigured-service")

	cfg2, err := ReconfigureTelemetry(context.Background())
	if err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}
	if cfg2 == nil {
		t.Fatal("expected non-nil config after reconfigure")
	}
	if cfg2 == cfg1 {
		t.Error("expected a fresh config pointer after reconfigure")
	}
	if cfg2.ServiceName != "reconfigured-service" {
		t.Errorf("expected ServiceName=%q after reconfigure, got %q", "reconfigured-service", cfg2.ServiceName)
	}
}
