// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import (
	"log/slog"
	"strings"

	"github.com/provide-io/provide-telemetry/go/internal/schemacore"
)

// EventRecord holds the structured DA(R)S fields for an event.
type EventRecord struct {
	Event    string
	Domain   string
	Action   string
	Resource string // empty for DAS form
	Status   string
}

// Attrs returns slog-compatible attributes for the structured event fields.
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
// strictSchema controls whether segment format validation is applied.
func Event(strictSchema bool, segments ...string) (EventRecord, error) {
	if err := schemacore.ValidateEventCall(strictSchema, segments); err != nil {
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
func EventName(strictSchema bool, segments ...string) (string, error) {
	if err := schemacore.ValidateEventSegments(strictSchema, segments); err != nil {
		return "", NewEventSchemaError(err.Error())
	}
	return strings.Join(segments, "."), nil
}

// ValidateEventName splits a dotted event name and validates its segments.
func ValidateEventName(strictSchema bool, name string) error {
	segments := strings.Split(name, ".")
	if err := schemacore.ValidateEventSegments(strictSchema, segments); err != nil {
		return NewEventSchemaError(err.Error())
	}
	return nil
}

// ValidateRequiredKeys returns an EventSchemaError if any required key is missing.
func ValidateRequiredKeys(attrs map[string]any, requiredKeys []string) error {
	if err := schemacore.ValidateRequiredKeys(attrs, requiredKeys); err != nil {
		return NewEventSchemaError(err.Error())
	}
	return nil
}
