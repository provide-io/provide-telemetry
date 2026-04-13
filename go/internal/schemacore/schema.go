// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Package schemacore contains the stateless event-schema validation logic
// shared by the top-level telemetry package and the logger sub-package.
package schemacore

import (
	"fmt"
	"regexp"
	"strings"
)

// SegmentRe matches a valid event name segment: starts with a lowercase letter,
// followed by lowercase letters, digits, or underscores.
var SegmentRe = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

// Segment count constants.
const (
	MinSegments  = 3
	MaxSegments  = 5
	DASSegments  = 3
	DARSSegments = 4
)

// ValidateSegmentFormat returns true if segment matches the required format.
func ValidateSegmentFormat(segment string) bool {
	return SegmentRe.MatchString(segment)
}

// ValidateEventSegments validates segment count and optionally segment format.
// If strictSchema is true, each segment must match ^[a-z][a-z0-9_]*$.
// Returns a non-nil error string suitable for wrapping in EventSchemaError.
func ValidateEventSegments(strictSchema bool, segments []string) error {
	n := len(segments)
	if n < MinSegments || n > MaxSegments {
		return fmt.Errorf("event name must have %d–%d segments, got %d",
			MinSegments, MaxSegments, n)
	}
	if strictSchema {
		for _, seg := range segments {
			if !ValidateSegmentFormat(seg) {
				return fmt.Errorf(
					"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg)
			}
		}
	}
	return nil
}

// ValidateEventCall validates the DA(R)S segment count (3 or 4 only) and
// optionally each segment's format.
func ValidateEventCall(strictSchema bool, segments []string) error {
	n := len(segments)
	if n != DASSegments && n != DARSSegments {
		return fmt.Errorf("event() requires 3 or 4 segments (DA[R]S), got %d", n)
	}
	if strictSchema {
		for _, seg := range segments {
			if !ValidateSegmentFormat(seg) {
				return fmt.Errorf(
					"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg)
			}
		}
	}
	return nil
}

// ValidateRequiredKeys returns an error if any required key is missing from attrs.
func ValidateRequiredKeys(attrs map[string]any, requiredKeys []string) error {
	for _, key := range requiredKeys {
		if _, ok := attrs[key]; !ok {
			return fmt.Errorf("missing required key: %s", key)
		}
	}
	return nil
}

// JoinSegments returns a dot-joined event name from segments.
func JoinSegments(segments []string) string {
	return strings.Join(segments, ".")
}
