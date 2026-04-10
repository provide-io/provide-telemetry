// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

// TelemetryError is the base error type for all provide-telemetry errors.
type TelemetryError struct {
	msg   string
	cause error
}

// Error returns the error message.
func (e *TelemetryError) Error() string { return e.msg }

// Unwrap returns the underlying cause, if any.
func (e *TelemetryError) Unwrap() error { return e.cause }

// NewTelemetryError creates a new TelemetryError with an optional cause.
func NewTelemetryError(msg string, cause ...error) *TelemetryError {
	var c error
	if len(cause) > 0 {
		c = cause[0]
	}
	return &TelemetryError{msg: msg, cause: c}
}

// ConfigurationError wraps TelemetryError for configuration problems.
type ConfigurationError struct{ *TelemetryError }

// As implements errors.As so that errors.As(cfgErr, &telemetryErrPtr) matches.
func (e *ConfigurationError) As(target interface{}) bool {
	if t, ok := target.(**TelemetryError); ok {
		*t = e.TelemetryError
		return true
	}
	return false
}

// NewConfigurationError creates a new ConfigurationError with an optional cause.
func NewConfigurationError(msg string, cause ...error) *ConfigurationError {
	var c error
	if len(cause) > 0 {
		c = cause[0]
	}
	return &ConfigurationError{TelemetryError: &TelemetryError{msg: msg, cause: c}}
}

// EventSchemaError wraps TelemetryError for event schema violations.
type EventSchemaError struct{ *TelemetryError }

// As implements errors.As so that errors.As(schemaErr, &telemetryErrPtr) matches.
func (e *EventSchemaError) As(target interface{}) bool {
	if t, ok := target.(**TelemetryError); ok {
		*t = e.TelemetryError
		return true
	}
	return false
}

// NewEventSchemaError creates a new EventSchemaError with an optional cause.
func NewEventSchemaError(msg string, cause ...error) *EventSchemaError {
	var c error
	if len(cause) > 0 {
		c = cause[0]
	}
	return &EventSchemaError{TelemetryError: &TelemetryError{msg: msg, cause: c}}
}
