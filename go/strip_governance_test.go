// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//go:build nogovernance

// strip_governance_test.go — regression tests for the no-governance build.
// Run with: go test -tags nogovernance ./...
//
// These tests assert that core telemetry features work correctly when
// classification, consent, and receipts modules are excluded.
package telemetry

import (
	"context"
	"testing"
)

// TestNoGovernance_SetupShutdownRoundtrip verifies setup/shutdown works without governance.
func TestNoGovernance_SetupShutdownRoundtrip(t *testing.T) {
	ctx := context.Background()
	_ = ShutdownTelemetry(ctx)
	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("setup must succeed without governance: %v", err)
	}
	if cfg.ServiceName == "" {
		t.Error("config must include a service name")
	}
	_ = ShutdownTelemetry(ctx)
}

// TestNoGovernance_LoggerUsable verifies the logger works without governance.
func TestNoGovernance_LoggerUsable(t *testing.T) {
	ctx := context.Background()
	log := GetLogger(ctx, "no-governance-test")
	if log == nil {
		t.Fatal("GetLogger must return a non-nil logger")
	}
	// No panic = success
	log.Info("no_governance.test.logged")
}

// TestNoGovernance_PIIRedactsDefaultSensitiveKeys verifies that default-sensitive
// keys are masked even without the classification module.
func TestNoGovernance_PIIRedactsDefaultSensitiveKeys(t *testing.T) {
	ReplacePIIRules(nil)
	payload := map[string]any{
		"user":     "alice",
		"password": "s3cr3t",
		"token":    "abc123",
	}
	result := SanitizePayload(payload, true, 3)
	if result["password"] != "***" {
		t.Errorf("password must be redacted, got %v", result["password"])
	}
	if result["token"] != "***" {
		t.Errorf("token must be redacted, got %v", result["token"])
	}
	if result["user"] != "alice" {
		t.Errorf("non-sensitive key must pass through, got %v", result["user"])
	}
	// No classification labels without governance
	if _, found := result["__password__class"]; found {
		t.Error("classification labels must be absent without governance")
	}
}

// TestNoGovernance_HealthSnapshotAvailable verifies health counters work without governance.
func TestNoGovernance_HealthSnapshotAvailable(t *testing.T) {
	snap := GetHealthSnapshot()
	if snap.LogsEmitted < 0 {
		t.Error("LogsEmitted must be non-negative")
	}
	if snap.LogsDropped < 0 {
		t.Error("LogsDropped must be non-negative")
	}
	if snap.TracesEmitted < 0 {
		t.Error("TracesEmitted must be non-negative")
	}
}

// TestNoGovernance_SamplingPolicyRoundtrip verifies sampling works without governance.
func TestNoGovernance_SamplingPolicyRoundtrip(t *testing.T) {
	policy := SamplingPolicy{DefaultRate: 0.5}
	if _, err := SetSamplingPolicy("logs", policy); err != nil {
		t.Fatalf("SetSamplingPolicy must not error: %v", err)
	}
	got, err := GetSamplingPolicy("logs")
	if err != nil {
		t.Fatalf("GetSamplingPolicy must not error: %v", err)
	}
	if got.DefaultRate != 0.5 {
		t.Errorf("expected default_rate=0.5, got %v", got.DefaultRate)
	}
	// Reset
	_, _ = SetSamplingPolicy("logs", SamplingPolicy{DefaultRate: 1.0})
}

// TestNoGovernance_CounterUsable verifies metric counters work without governance.
func TestNoGovernance_CounterUsable(t *testing.T) {
	ctx := context.Background()
	c := NewCounter("no_governance.test.counter")
	if c == nil {
		t.Fatal("NewCounter must return a non-nil instrument")
	}
	// No panic on increment
	c.Add(ctx, 1)
}
