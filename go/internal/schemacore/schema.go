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

// ValidateEventSegments validates event-name segments under the shared
// five-language contract.
//
// Relaxed (the default) accepts one or more segments and enforces no grammar.
// Strict accepts MinSegments..MaxSegments and requires every segment to match
// SegmentRe. Zero segments and empty segments fail in both modes.
//
// This is deliberately more permissive than the pre-2026-08-20 Go behaviour,
// which enforced the 3–5 count regardless of mode while Python, TypeScript and
// Rust accepted any non-empty segment list in relaxed mode. See CHANGELOG.
// It is also stricter in one respect: relaxed mode used to accept an empty
// segment, so EventName("user", "", "ok") and ValidateEventName("a..b") both
// passed.
//
// ValidateEventCall is a separate contract and is not affected: event() builds
// a positional DAS/DARS record, so its 3-or-4 rule belongs to the record shape
// rather than to the name.
func ValidateEventSegments(strictSchema bool, segments []string) error {
	if len(segments) == 0 {
		return fmt.Errorf("event name requires at least 1 segment, got 0")
	}
	for _, seg := range segments {
		if seg == "" {
			return fmt.Errorf("event name segments must be non-empty")
		}
	}
	if !strictSchema {
		return nil
	}
	if n := len(segments); n < MinSegments || n > MaxSegments {
		return fmt.Errorf("event name must have %d–%d segments, got %d",
			MinSegments, MaxSegments, n)
	}
	for _, seg := range segments {
		if !ValidateSegmentFormat(seg) {
			return fmt.Errorf(
				"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg)
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
