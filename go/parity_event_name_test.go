// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry_test

import (
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// Executable evidence for the event_name_contract fixtures in
// spec/behavioral_fixtures.yaml — one test per case, in fixture order.

func relaxedSchema(t *testing.T) {
	t.Helper()
	telemetry.SetStrictSchema(false)
	t.Cleanup(func() { telemetry.SetStrictSchema(false) })
}

func strictSchema(t *testing.T) {
	t.Helper()
	telemetry.SetStrictSchema(true)
	t.Cleanup(func() { telemetry.SetStrictSchema(false) })
}

func assertEventName(t *testing.T, want string, got string, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("EventName rejected a valid name: %v", err)
	}
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestParity_EventName_RelaxedSingleSegmentOK(t *testing.T) {
	relaxedSchema(t)
	got, err := telemetry.EventName("startup")
	assertEventName(t, "startup", got, err)
}

func TestParity_EventName_RelaxedTwoSegmentsOK(t *testing.T) {
	relaxedSchema(t)
	got, err := telemetry.EventName("app", "ready")
	assertEventName(t, "app.ready", got, err)
}

func TestParity_EventName_RelaxedSixSegmentsOK(t *testing.T) {
	relaxedSchema(t)
	got, err := telemetry.EventName("a", "b", "c", "d", "e", "f")
	assertEventName(t, "a.b.c.d.e.f", got, err)
}

func TestParity_EventName_RelaxedGrammarNotEnforced(t *testing.T) {
	relaxedSchema(t)
	got, err := telemetry.EventName("User", "Login-OK")
	assertEventName(t, "User.Login-OK", got, err)
}

func TestParity_EventName_RelaxedZeroSegmentsError(t *testing.T) {
	relaxedSchema(t)
	if _, err := telemetry.EventName(); err == nil {
		t.Fatal("zero segments must fail in relaxed mode")
	}
}

func TestParity_EventName_RelaxedEmptySegmentError(t *testing.T) {
	relaxedSchema(t)
	if _, err := telemetry.EventName("user", "", "ok"); err == nil {
		t.Fatal("an empty segment must fail in relaxed mode")
	}
}

func TestParity_EventName_StrictThreeSegmentsOK(t *testing.T) {
	strictSchema(t)
	got, err := telemetry.EventName("user", "login", "ok")
	assertEventName(t, "user.login.ok", got, err)
}

func TestParity_EventName_StrictFiveSegmentsOK(t *testing.T) {
	strictSchema(t)
	got, err := telemetry.EventName("a", "b", "c", "d", "e")
	assertEventName(t, "a.b.c.d.e", got, err)
}

func TestParity_EventName_StrictTwoSegmentsError(t *testing.T) {
	strictSchema(t)
	if _, err := telemetry.EventName("too", "few"); err == nil {
		t.Fatal("2 segments must fail in strict mode")
	}
}

func TestParity_EventName_StrictSixSegmentsError(t *testing.T) {
	strictSchema(t)
	if _, err := telemetry.EventName("a", "b", "c", "d", "e", "f"); err == nil {
		t.Fatal("6 segments must fail in strict mode")
	}
}

func TestParity_EventName_StrictGrammarEnforced(t *testing.T) {
	strictSchema(t)
	if _, err := telemetry.EventName("user", "Login", "ok"); err == nil {
		t.Fatal("a grammar violation must fail in strict mode")
	}
}

func TestParity_EventName_StrictZeroSegmentsError(t *testing.T) {
	strictSchema(t)
	if _, err := telemetry.EventName(); err == nil {
		t.Fatal("zero segments must fail in strict mode")
	}
}

func TestParity_ValidateEventName_RelaxedSingleSegmentOK(t *testing.T) {
	relaxedSchema(t)
	if err := telemetry.ValidateEventName("startup"); err != nil {
		t.Fatalf("relaxed 1-segment dotted name rejected: %v", err)
	}
}

func TestParity_ValidateEventName_RelaxedEmptyStringError(t *testing.T) {
	relaxedSchema(t)
	if err := telemetry.ValidateEventName(""); err == nil {
		t.Fatal(`"" must fail: it is one empty segment, not zero segments`)
	}
}

func TestParity_ValidateEventName_RelaxedInteriorEmptySegmentError(t *testing.T) {
	relaxedSchema(t)
	if err := telemetry.ValidateEventName("a..b"); err == nil {
		t.Fatal(`"a..b" must fail: interior empty segment`)
	}
}

func TestParity_ValidateEventName_RelaxedGrammarNotEnforced(t *testing.T) {
	relaxedSchema(t)
	if err := telemetry.ValidateEventName("User.Login-OK"); err != nil {
		t.Fatalf("relaxed mode must not enforce grammar: %v", err)
	}
}

func TestParity_ValidateEventName_StrictGrammarEnforced(t *testing.T) {
	strictSchema(t)
	if err := telemetry.ValidateEventName("user.Login.ok"); err == nil {
		t.Fatal("strict mode must enforce grammar")
	}
}

func TestParity_ValidateEventName_StrictTwoSegmentsError(t *testing.T) {
	strictSchema(t)
	if err := telemetry.ValidateEventName("too.few"); err == nil {
		t.Fatal("2 segments must fail in strict mode")
	}
}

// Event() is out of scope for the 2026-08-20 contract change: its count rule is
// a property of the DAS/DARS record shape, not of the name, so relaxing the
// name contract must not move it.
func TestParity_Event_CountRuleUnchangedByRelaxedMode(t *testing.T) {
	relaxedSchema(t)
	if _, err := telemetry.Event("only", "two"); err == nil {
		t.Fatal("Event() must still require 3 or 4 segments in relaxed mode")
	}
	if _, err := telemetry.Event("a", "b", "c", "d", "e"); err == nil {
		t.Fatal("Event() must still reject 5 segments in relaxed mode")
	}
}
