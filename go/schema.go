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
var _strictSchema bool

const (
	_minSegments = 3
	_maxSegments = 5
)

// EventName validates and returns a dotted event name from segments.
// Returns an *EventSchemaError if the segment count or format is invalid.
// When _strictSchema is false the name is still always validated; callers
// receive the error and may choose to ignore it.
func EventName(segments ...string) (string, error) {
	name := strings.Join(segments, ".")
	if err := validateSegments(segments); err != nil {
		return "", err
	}
	return name, nil
}

// ValidateEventName splits a dotted event name string and validates its segments.
// Returns an *EventSchemaError if invalid, nil otherwise.
func ValidateEventName(name string) error {
	segments := strings.Split(name, ".")
	return validateSegments(segments)
}

// validateSegments checks segment count and per-segment format rules.
func validateSegments(segments []string) error {
	n := len(segments)
	if n < _minSegments || n > _maxSegments {
		return NewEventSchemaError(fmt.Sprintf(
			"event name must have %d–%d segments, got %d",
			_minSegments, _maxSegments, n,
		))
	}
	for _, seg := range segments {
		if !_segmentRe.MatchString(seg) {
			return NewEventSchemaError(fmt.Sprintf(
				"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg,
			))
		}
	}
	return nil
}
