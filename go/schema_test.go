// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"errors"
	"strings"
	"testing"
)

func TestEventName_Valid(t *testing.T) {
	cases := []struct {
		name     string
		segments []string
		wantName string
	}{
		{
			name:     "exactly 3 segments",
			segments: []string{"provide", "telemetry", "setup"},
			wantName: "provide.telemetry.setup",
		},
		{
			name:     "exactly 5 segments",
			segments: []string{"provide", "telemetry", "setup", "complete", "ok"},
			wantName: "provide.telemetry.setup.complete.ok",
		},
		{
			name:     "4 segments",
			segments: []string{"provide", "telemetry", "setup", "done"},
			wantName: "provide.telemetry.setup.done",
		},
		{
			name:     "segment with digits and underscores",
			segments: []string{"a1", "b2_c3", "d4e5"},
			wantName: "a1.b2_c3.d4e5",
		},
		{
			name:     "segment starts with letter followed by underscore",
			segments: []string{"my_module", "sub_component", "event_fired"},
			wantName: "my_module.sub_component.event_fired",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := EventName(tc.segments...)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tc.wantName {
				t.Errorf("want %q, got %q", tc.wantName, got)
			}
		})
	}
}

func TestEventName_Invalid(t *testing.T) {
	cases := []struct {
		name        string
		segments    []string
		errContains string
	}{
		{
			name:        "too few segments (2)",
			segments:    []string{"provide", "telemetry"},
			errContains: "3",
		},
		{
			name:        "too many segments (6)",
			segments:    []string{"a", "b", "c", "d", "e", "f"},
			errContains: "6",
		},
		{
			name:        "uppercase in segment",
			segments:    []string{"Provide", "telemetry", "setup"},
			errContains: "Provide",
		},
		{
			name:        "segment starting with digit",
			segments:    []string{"1provide", "telemetry", "setup"},
			errContains: "1provide",
		},
		{
			name:        "empty segment",
			segments:    []string{"", "telemetry", "setup"},
			errContains: "",
		},
		{
			name:        "segment with hyphen",
			segments:    []string{"provide-io", "telemetry", "setup"},
			errContains: "provide-io",
		},
		{
			name:        "segment with space",
			segments:    []string{"provide io", "telemetry", "setup"},
			errContains: "provide io",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := EventName(tc.segments...)
			if err == nil {
				t.Fatalf("expected error, got name %q", got)
			}
			var schemaErr *EventSchemaError
			if !errors.As(err, &schemaErr) {
				t.Errorf("expected *EventSchemaError, got %T: %v", err, err)
			}
			if tc.errContains != "" && !strings.Contains(err.Error(), tc.errContains) {
				t.Errorf("error %q should contain %q", err.Error(), tc.errContains)
			}
			if got != "" {
				t.Errorf("on error expected empty name, got %q", got)
			}
		})
	}
}

func TestEventName_ZeroSegments(t *testing.T) {
	_, err := EventName()
	if err == nil {
		t.Fatal("expected error for zero segments")
	}
	var schemaErr *EventSchemaError
	if !errors.As(err, &schemaErr) {
		t.Errorf("expected *EventSchemaError, got %T", err)
	}
}

func TestValidateEventName_Valid(t *testing.T) {
	cases := []string{
		"provide.telemetry.setup",
		"provide.telemetry.setup.done",
		"provide.telemetry.setup.complete.ok",
	}
	for _, name := range cases {
		t.Run(name, func(t *testing.T) {
			if err := ValidateEventName(name); err != nil {
				t.Errorf("unexpected error for %q: %v", name, err)
			}
		})
	}
}

func TestValidateEventName_Invalid(t *testing.T) {
	cases := []struct {
		name        string
		errContains string
	}{
		{"too.short", "2"},
		{"a.b.c.d.e.f", "6"},
		{"Provide.telemetry.setup", "Provide"},
		{"1start.telemetry.setup", "1start"},
		{"provide.telemetry.bad-seg", "bad-seg"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := ValidateEventName(tc.name)
			if err == nil {
				t.Fatalf("expected error for %q", tc.name)
			}
			var schemaErr *EventSchemaError
			if !errors.As(err, &schemaErr) {
				t.Errorf("expected *EventSchemaError, got %T: %v", err, err)
			}
			if tc.errContains != "" && !strings.Contains(err.Error(), tc.errContains) {
				t.Errorf("error %q should contain %q", err.Error(), tc.errContains)
			}
		})
	}
}

func TestValidateEventName_RoundTrip(t *testing.T) {
	segments := []string{"provide", "telemetry", "event"}
	name, err := EventName(segments...)
	if err != nil {
		t.Fatalf("EventName: %v", err)
	}
	if err := ValidateEventName(name); err != nil {
		t.Errorf("ValidateEventName round-trip failed: %v", err)
	}
}
