// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
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

func TestGetRuntimeConfigReturnsDefensiveCopy(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config after setup")
	}
	cfg.ServiceName = "mutated-locally"

	again := GetRuntimeConfig()
	if again == nil {
		t.Fatal("expected non-nil config after second read")
	}
	if again.ServiceName == "mutated-locally" {
		t.Fatal("mutating GetRuntimeConfig result should not mutate runtime state")
	}
}

func TestCloneTelemetryConfigNilAndDeepCopy(t *testing.T) {
	if cloneTelemetryConfig(nil) != nil {
		t.Fatal("expected nil clone for nil input")
	}

	cfg := DefaultTelemetryConfig()
	cfg.Logging.OTLPHeaders["Authorization"] = "Bearer token"
	cfg.Logging.PrettyFields = []string{"event"}
	cfg.Logging.ModuleLevels["pkg"] = "DEBUG"
	cfg.EventSchema.RequiredKeys = []string{"request_id"}

	clone := cloneTelemetryConfig(cfg)
	if clone == nil {
		t.Fatal("expected non-nil clone")
	}

	clone.Logging.OTLPHeaders["Authorization"] = "changed"
	clone.Logging.PrettyFields[0] = "msg"
	clone.Logging.ModuleLevels["pkg"] = "INFO"
	clone.EventSchema.RequiredKeys[0] = "session_id"

	if cfg.Logging.OTLPHeaders["Authorization"] != "Bearer token" {
		t.Fatal("logging headers should be deep copied")
	}
	if cfg.Logging.PrettyFields[0] != "event" {
		t.Fatal("pretty fields should be deep copied")
	}
	if cfg.Logging.ModuleLevels["pkg"] != "DEBUG" {
		t.Fatal("module levels should be deep copied")
	}
	if cfg.EventSchema.RequiredKeys[0] != "request_id" {
		t.Fatal("required keys should be deep copied")
	}
}

func TestRuntimeOverridesPreservesUnsetFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	before := GetRuntimeConfig()
	if before == nil {
		t.Fatal("expected non-nil config")
	}

	// Apply an empty overrides — nothing should change.
	err := UpdateRuntimeConfig(RuntimeOverrides{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	after := GetRuntimeConfig()
	if after == nil {
		t.Fatal("expected non-nil config")
	}

	// All fields should be preserved.
	if after.Sampling != before.Sampling {
		t.Errorf("Sampling changed: before=%+v after=%+v", before.Sampling, after.Sampling)
	}
	if after.Backpressure != before.Backpressure {
		t.Errorf("Backpressure changed: before=%+v after=%+v", before.Backpressure, after.Backpressure)
	}
	if after.Security != before.Security {
		t.Errorf("Security changed: before=%+v after=%+v", before.Security, after.Security)
	}
	if after.SLO != before.SLO {
		t.Errorf("SLO changed: before=%+v after=%+v", before.SLO, after.SLO)
	}
	if after.ServiceName != before.ServiceName {
		t.Errorf("ServiceName changed: before=%q after=%q", before.ServiceName, after.ServiceName)
	}
	if after.Logging.PIIMaxDepth != before.Logging.PIIMaxDepth {
		t.Errorf("PIIMaxDepth changed: before=%d after=%d", before.Logging.PIIMaxDepth, after.Logging.PIIMaxDepth)
	}
}

func ptrInt(v int) *int {
	return &v
}
