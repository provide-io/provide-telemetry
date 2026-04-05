// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"regexp"
	"strings"
)

// _segmentRe matches a valid event name segment: starts with a lowercase letter,
// followed by lowercase letters, digits, or underscores.
var _segmentRe = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

// _strictSchema controls whether EventName enforces validation.
// Set to true by SetupTelemetry when StrictSchema is enabled.
var _strictSchema bool //nolint:unused

const (
	_minSegments = 3
	_maxSegments = 5
)

// EventName validates and returns a dotted event name from segments.
// Accepts 3–5 segments. Format validation is only applied when _strictSchema is true.
func EventName(segments ...string) (string, error) {
	n := len(segments)
	if n < _minSegments || n > _maxSegments {
		return "", NewEventSchemaError(fmt.Sprintf(
			"event name must have %d–%d segments, got %d",
			_minSegments, _maxSegments, n,
		))
	}
	if _strictSchema {
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

// ValidateEventName splits a dotted event name string and validates its segments.
// Returns an *EventSchemaError if invalid, nil otherwise.
// Segment count is always enforced; format validation only applies when _strictSchema is true.
func ValidateEventName(name string) error {
	segments := strings.Split(name, ".")
	n := len(segments)
	if n < _minSegments || n > _maxSegments {
		return NewEventSchemaError(fmt.Sprintf(
			"event name must have %d–%d segments, got %d",
			_minSegments, _maxSegments, n,
		))
	}
	if _strictSchema {
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

// ValidateRequiredKeys returns an EventSchemaError if any required key is missing from attrs.
func ValidateRequiredKeys(attrs map[string]any, requiredKeys []string) error {
	for _, key := range requiredKeys {
		if _, ok := attrs[key]; !ok {
			return NewEventSchemaError("missing required key: " + key)
		}
	}
	return nil
}
