// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import (
	"fmt"
	"log/slog"
	"regexp"
	"strings"
)

var _segmentRe = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

const (
	_minSegments  = 3
	_maxSegments  = 5
	_dasSegments  = 3
	_darsSegments = 4
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
	n := len(segments)
	if n != _dasSegments && n != _darsSegments {
		return EventRecord{}, NewEventSchemaError(fmt.Sprintf(
			"event() requires 3 or 4 segments (DA[R]S), got %d", n,
		))
	}
	if strictSchema {
		for _, seg := range segments {
			if !_segmentRe.MatchString(seg) {
				return EventRecord{}, NewEventSchemaError(fmt.Sprintf(
					"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg,
				))
			}
		}
	}
	name := strings.Join(segments, ".")
	if n == _dasSegments {
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
	n := len(segments)
	if n < _minSegments || n > _maxSegments {
		return "", NewEventSchemaError(fmt.Sprintf(
			"event name must have %d–%d segments, got %d", _minSegments, _maxSegments, n,
		))
	}
	if strictSchema {
		for _, seg := range segments {
			if !_segmentRe.MatchString(seg) {
				return "", NewEventSchemaError(fmt.Sprintf(
					"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg,
				))
			}
		}
	}
	return strings.Join(segments, "."), nil
}

// ValidateEventName splits a dotted event name and validates its segments.
func ValidateEventName(strictSchema bool, name string) error {
	segments := strings.Split(name, ".")
	n := len(segments)
	if n < _minSegments || n > _maxSegments {
		return NewEventSchemaError(fmt.Sprintf(
			"event name must have %d–%d segments, got %d", _minSegments, _maxSegments, n,
		))
	}
	if strictSchema {
		for _, seg := range segments {
			if !_segmentRe.MatchString(seg) {
				return NewEventSchemaError(fmt.Sprintf(
					"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg,
				))
			}
		}
	}
	return nil
}

// ValidateRequiredKeys returns an EventSchemaError if any required key is missing.
func ValidateRequiredKeys(attrs map[string]any, requiredKeys []string) error {
	for _, key := range requiredKeys {
		if _, ok := attrs[key]; !ok {
			return NewEventSchemaError("missing required key: " + key)
		}
	}
	return nil
}
