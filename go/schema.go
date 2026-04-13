// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"log/slog"
	"strings"
	"sync"

	"github.com/provide-io/provide-telemetry/go/internal/schemacore"
)

// _strictSchema controls whether Event enforces segment format validation.
// Set to true by SetupTelemetry when StrictSchema is enabled.
// Protected by _strictSchemaMu for concurrent access via SetStrictSchema/GetStrictSchema.
var (
	_strictSchema   bool
	_strictSchemaMu sync.RWMutex
)

// SetStrictSchema enables or disables strict segment-format validation for Event and EventName.
//
// When enabled, every segment must match ^[a-z][a-z0-9_]*$. When disabled (the default),
// segment format is not validated. Segment count validation (3–4 for Event, 3–5 for EventName)
// is always enforced regardless of this flag.
//
// This function is safe for concurrent use and can be called at any time — before or after
// SetupTelemetry. SetupTelemetry will overwrite this flag with the config value on startup.
func SetStrictSchema(enabled bool) {
	_strictSchemaMu.Lock()
	_strictSchema = enabled
	_strictSchemaMu.Unlock()
}

// GetStrictSchema returns the current strict-schema flag value.
// Safe for concurrent use.
func GetStrictSchema() bool {
	_strictSchemaMu.RLock()
	defer _strictSchemaMu.RUnlock()
	return _strictSchema
}

// _readStrictSchema reads _strictSchema under a read lock for use by Event/EventName.
func _readStrictSchema() bool {
	_strictSchemaMu.RLock()
	defer _strictSchemaMu.RUnlock()
	return _strictSchema
}

// EventRecord holds the structured DA(R)S fields for an event.
// The Event field is the dot-joined name (e.g. "auth.login.success").
// Resource is empty string in DAS (3-segment) form.
type EventRecord struct {
	Event    string
	Domain   string
	Action   string
	Resource string // empty for DAS form
	Status   string
}

// Attrs returns slog-compatible attributes for the structured event fields as
// a []any slice suitable for spreading into log.InfoContext / log.ErrorContext:
//
//	evt, _ := telemetry.Event("auth", "login", "success")
//	log.InfoContext(ctx, evt.Event, evt.Attrs()...)
//
// Each element is a slog.Attr. Resource is only included for DARS (4-segment) events.
func (e EventRecord) Attrs() []any {
	attrs := []any{
		slog.String("event.domain", e.Domain),
		slog.String("event.action", e.Action),
		slog.String("event.status", e.Status),
	}
	if e.Resource != "" {
		attrs = append(attrs, slog.String("event.resource", e.Resource))
	}
	return attrs
}

// Event validates segments and returns a structured EventRecord.
// Accepts exactly 3 segments (DAS: domain.action.status) or
// 4 segments (DARS: domain.action.resource.status).
//
// The segment count is always enforced. Segment format validation
// (^[a-z][a-z0-9_]*$) is only applied when _strictSchema is true.
//
// Returns an *EventSchemaError if validation fails.
func Event(segments ...string) (EventRecord, error) {
	if err := schemacore.ValidateEventCall(_readStrictSchema(), segments); err != nil {
		return EventRecord{}, NewEventSchemaError(err.Error())
	}
	name := schemacore.JoinSegments(segments)
	n := len(segments)
	if n == schemacore.DASSegments {
		return EventRecord{
			Event:  name,
			Domain: segments[0],
			Action: segments[1],
			Status: segments[2],
		}, nil
	}
	return EventRecord{
		Event:    name,
		Domain:   segments[0],
		Action:   segments[1],
		Resource: segments[2],
		Status:   segments[3],
	}, nil
}

// EventName validates and returns a dotted event name from segments.
// Accepts 3–5 segments. Format validation is only applied when _strictSchema is true.
func EventName(segments ...string) (string, error) {
	if err := schemacore.ValidateEventSegments(_readStrictSchema(), segments); err != nil {
		return "", NewEventSchemaError(err.Error())
	}
	return strings.Join(segments, "."), nil
}

// ValidateEventName splits a dotted event name string and validates its segments.
// Returns an *EventSchemaError if invalid, nil otherwise.
// Segment count is always enforced; format validation only applies when _strictSchema is true.
func ValidateEventName(name string) error {
	segments := strings.Split(name, ".")
	if err := schemacore.ValidateEventSegments(_readStrictSchema(), segments); err != nil {
		return NewEventSchemaError(err.Error())
	}
	return nil
}

// ValidateRequiredKeys returns an EventSchemaError if any required key is missing from attrs.
func ValidateRequiredKeys(attrs map[string]any, requiredKeys []string) error {
	if err := schemacore.ValidateRequiredKeys(attrs, requiredKeys); err != nil {
		return NewEventSchemaError(err.Error())
	}
	return nil
}
