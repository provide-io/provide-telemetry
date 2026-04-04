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
	// ConfigurationError embeds *TelemetryError by pointer; errors.As correctly matches *TelemetryError.
	if !errors.As(err, &target) {
		t.Errorf("errors.As should match *TelemetryError for *ConfigurationError (embedded by pointer)")
	}
	if target.Error() != "cfg" {
		t.Errorf("expected %q, got %q", "cfg", target.Error())
	}
}

func TestEventSchemaError_AsTelemetryError(t *testing.T) {
	err := NewEventSchemaError("schema")
	var target *TelemetryError
	// EventSchemaError embeds *TelemetryError by pointer; errors.As correctly matches *TelemetryError.
	if !errors.As(err, &target) {
		t.Errorf("errors.As should match *TelemetryError for *EventSchemaError (embedded by pointer)")
	}
	if target.Error() != "schema" {
		t.Errorf("expected %q, got %q", "schema", target.Error())
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

func TestConfigurationError_As_WrongType(t *testing.T) {
	// Verify As returns false for a non-matching target type.
	cfgErr := NewConfigurationError("cfg")
	var target *EventSchemaError
	if errors.As(cfgErr, &target) {
		t.Error("errors.As should not match *EventSchemaError for *ConfigurationError")
	}
}

func TestEventSchemaError_As_WrongType(t *testing.T) {
	// Verify As returns false for a non-matching target type.
	schemaErr := NewEventSchemaError("schema")
	var target *ConfigurationError
	if errors.As(schemaErr, &target) {
		t.Error("errors.As should not match *ConfigurationError for *EventSchemaError")
	}
}
