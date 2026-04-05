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
	// Format validation (segment content) requires strict mode.
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })

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
	// Format validation (segment content) requires strict mode.
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })

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

func TestEvent_DAS(t *testing.T) {
	evt, err := Event("auth", "login", "success")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if evt.Event != "auth.login.success" {
		t.Errorf("want Event=%q, got %q", "auth.login.success", evt.Event)
	}
	if evt.Domain != "auth" {
		t.Errorf("want Domain=%q, got %q", "auth", evt.Domain)
	}
	if evt.Action != "login" {
		t.Errorf("want Action=%q, got %q", "login", evt.Action)
	}
	if evt.Resource != "" {
		t.Errorf("want empty Resource, got %q", evt.Resource)
	}
	if evt.Status != "success" {
		t.Errorf("want Status=%q, got %q", "success", evt.Status)
	}
}

func TestEvent_DARS(t *testing.T) {
	evt, err := Event("payment", "subscription", "renewal", "success")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if evt.Event != "payment.subscription.renewal.success" {
		t.Errorf("want Event=%q, got %q", "payment.subscription.renewal.success", evt.Event)
	}
	if evt.Domain != "payment" {
		t.Errorf("want Domain=%q, got %q", "payment", evt.Domain)
	}
	if evt.Action != "subscription" {
		t.Errorf("want Action=%q, got %q", "subscription", evt.Action)
	}
	if evt.Resource != "renewal" {
		t.Errorf("want Resource=%q, got %q", "renewal", evt.Resource)
	}
	if evt.Status != "success" {
		t.Errorf("want Status=%q, got %q", "success", evt.Status)
	}
}

func TestEvent_TwoArgs_Error(t *testing.T) {
	_, err := Event("auth", "login")
	if err == nil {
		t.Fatal("expected error for 2 segments")
	}
	var schemaErr *EventSchemaError
	if !errors.As(err, &schemaErr) {
		t.Errorf("expected *EventSchemaError, got %T: %v", err, err)
	}
}

func TestEvent_FiveArgs_Error(t *testing.T) {
	_, err := Event("auth", "login", "user", "detail", "success")
	if err == nil {
		t.Fatal("expected error for 5 segments")
	}
	var schemaErr *EventSchemaError
	if !errors.As(err, &schemaErr) {
		t.Errorf("expected *EventSchemaError, got %T: %v", err, err)
	}
}

func TestEvent_InvalidSegment_StrictMode(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })

	_, err := Event("Auth", "login", "success")
	if err == nil {
		t.Fatal("expected error for uppercase segment in strict mode")
	}
	var schemaErr *EventSchemaError
	if !errors.As(err, &schemaErr) {
		t.Errorf("expected *EventSchemaError, got %T: %v", err, err)
	}
	if !strings.Contains(err.Error(), "Auth") {
		t.Errorf("error %q should mention invalid segment %q", err.Error(), "Auth")
	}
}

func TestEvent_InvalidSegment_NonStrictMode(t *testing.T) {
	_strictSchema = false
	evt, err := Event("Auth", "Login", "Success")
	if err != nil {
		t.Fatalf("unexpected error in non-strict mode: %v", err)
	}
	if evt.Event != "Auth.Login.Success" {
		t.Errorf("want %q, got %q", "Auth.Login.Success", evt.Event)
	}
}

func TestEventRecord_Attrs_DAS(t *testing.T) {
	evt := EventRecord{
		Event:  "auth.login.success",
		Domain: "auth",
		Action: "login",
		Status: "success",
	}
	attrs := evt.Attrs()
	if len(attrs) != 3 {
		t.Fatalf("want 3 attrs for DAS, got %d", len(attrs))
	}
	type kv struct{ key, val string }
	want := []kv{
		{"event.domain", "auth"},
		{"event.action", "login"},
		{"event.status", "success"},
	}
	for i, a := range attrs {
		sa, ok := a.(slog.Attr)
		if !ok {
			t.Fatalf("attr[%d] is not slog.Attr: %T", i, a)
		}
		if sa.Key != want[i].key {
			t.Errorf("attr[%d] key: want %q, got %q", i, want[i].key, sa.Key)
		}
		if sa.Value.String() != want[i].val {
			t.Errorf("attr[%d] val: want %q, got %q", i, want[i].val, sa.Value.String())
		}
	}
}

func TestValidateRequiredKeys_AllPresent(t *testing.T) {
	attrs := map[string]any{"domain": "user", "action": "login"}
	err := ValidateRequiredKeys(attrs, []string{"domain", "action"})
	if err != nil {
		t.Errorf("expected no error, got %v", err)
	}
}

func TestValidateRequiredKeys_MissingKey(t *testing.T) {
	attrs := map[string]any{"domain": "user"}
	err := ValidateRequiredKeys(attrs, []string{"domain", "action"})
	if err == nil {
		t.Error("expected error for missing required key 'action'")
	}
}

func TestValidateRequiredKeys_EmptyRequired(t *testing.T) {
	attrs := map[string]any{"domain": "user"}
	err := ValidateRequiredKeys(attrs, nil)
	if err != nil {
		t.Errorf("expected no error with nil required keys, got %v", err)
	}
}

func TestEventRecord_Attrs_DARS(t *testing.T) {
	evt := EventRecord{
		Event:    "payment.subscription.renewal.success",
		Domain:   "payment",
		Action:   "subscription",
		Resource: "renewal",
		Status:   "success",
	}
	attrs := evt.Attrs()
	if len(attrs) != 4 {
		t.Fatalf("want 4 attrs for DARS, got %d", len(attrs))
	}
	found := false
	for _, a := range attrs {
		sa, ok := a.(slog.Attr)
		if !ok {
			t.Fatalf("attr element is not slog.Attr: %T", a)
		}
		if sa.Key == "event.resource" && sa.Value.String() == "renewal" {
			found = true
		}
	}
	if !found {
		t.Error("expected event.resource=renewal in attrs")
	}
}
