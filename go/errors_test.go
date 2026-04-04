// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"errors"
	"fmt"
	"testing"
)

func TestTelemetryError_NoCause(t *testing.T) {
	err := NewTelemetryError("something went wrong")
	if err.Error() != "something went wrong" {
		t.Errorf("expected %q, got %q", "something went wrong", err.Error())
	}
	if err.Unwrap() != nil {
		t.Errorf("expected nil cause, got %v", err.Unwrap())
	}
}

func TestTelemetryError_WithCause(t *testing.T) {
	cause := errors.New("root cause")
	err := NewTelemetryError("wrapped", cause)
	if err.Error() != "wrapped" {
		t.Errorf("expected %q, got %q", "wrapped", err.Error())
	}
	if !errors.Is(err, cause) {
		t.Errorf("errors.Is failed: expected cause to be unwrapped")
	}
}

func TestConfigurationError_NoCause(t *testing.T) {
	err := NewConfigurationError("bad config")
	if err.Error() != "bad config" {
		t.Errorf("expected %q, got %q", "bad config", err.Error())
	}
	if err.Unwrap() != nil {
		t.Errorf("expected nil cause, got %v", err.Unwrap())
	}
}

func TestConfigurationError_WithCause(t *testing.T) {
	cause := fmt.Errorf("parse failure")
	err := NewConfigurationError("config invalid", cause)
	if !errors.Is(err, cause) {
		t.Errorf("errors.Is failed for ConfigurationError")
	}
}

func TestConfigurationError_As(t *testing.T) {
	err := NewConfigurationError("config err")
	var target *ConfigurationError
	if !errors.As(err, &target) {
		t.Errorf("errors.As failed for ConfigurationError")
	}
	if target.Error() != "config err" {
		t.Errorf("expected %q, got %q", "config err", target.Error())
	}
}

func TestConfigurationError_AsTelemetryError(t *testing.T) {
	err := NewConfigurationError("cfg")
	var target *TelemetryError
	// ConfigurationError embeds TelemetryError by value, not pointer; errors.As won't match *TelemetryError.
	// This verifies the expected (non-matching) behaviour.
	if errors.As(err, &target) {
		t.Errorf("errors.As should NOT match *TelemetryError for *ConfigurationError (embedded by value)")
	}
}

func TestEventSchemaError_NoCause(t *testing.T) {
	err := NewEventSchemaError("bad schema")
	if err.Error() != "bad schema" {
		t.Errorf("expected %q, got %q", "bad schema", err.Error())
	}
	if err.Unwrap() != nil {
		t.Errorf("expected nil cause, got %v", err.Unwrap())
	}
}

func TestEventSchemaError_WithCause(t *testing.T) {
	cause := errors.New("schema parse error")
	err := NewEventSchemaError("invalid event", cause)
	if !errors.Is(err, cause) {
		t.Errorf("errors.Is failed for EventSchemaError")
	}
}

func TestEventSchemaError_As(t *testing.T) {
	err := NewEventSchemaError("schema err")
	var target *EventSchemaError
	if !errors.As(err, &target) {
		t.Errorf("errors.As failed for EventSchemaError")
	}
	if target.Error() != "schema err" {
		t.Errorf("expected %q, got %q", "schema err", target.Error())
	}
}

func TestTelemetryError_As(t *testing.T) {
	err := NewTelemetryError("tel err")
	var target *TelemetryError
	if !errors.As(err, &target) {
		t.Errorf("errors.As failed for TelemetryError")
	}
}

func TestAllErrorsImplementError(t *testing.T) {
	// Verify all three satisfy the error interface.
	var _ error = NewTelemetryError("x")
	var _ error = NewConfigurationError("x")
	var _ error = NewEventSchemaError("x")
}
