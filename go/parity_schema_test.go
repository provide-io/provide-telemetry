// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_schema_test.go validates Go behavioral parity for event schema against
// spec/behavioral_fixtures.yaml: DAS and DARS event construction, arity errors
// (too few/too many args), and strict vs lenient EventName validation
// (uppercase acceptance in lenient mode, rejection in strict mode).

package telemetry

import (
	"testing"
)

// ── Event DARS ───────────────────────────────────────────────────────────────

func TestParity_Event_DAS(t *testing.T) {
	evt, err := Event("user", "login", "ok")
	if err != nil {
		t.Fatalf("Event(user,login,ok) error: %v", err)
	}
	if evt.Event != "user.login.ok" {
		t.Errorf("event: want user.login.ok, got %q", evt.Event)
	}
	if evt.Domain != "user" || evt.Action != "login" || evt.Status != "ok" {
		t.Errorf("fields: got domain=%q action=%q status=%q", evt.Domain, evt.Action, evt.Status)
	}
	if evt.Resource != "" {
		t.Errorf("resource: want empty for DAS, got %q", evt.Resource)
	}
}

func TestParity_Event_DARS(t *testing.T) {
	evt, err := Event("db", "query", "users", "ok")
	if err != nil {
		t.Fatalf("Event(db,query,users,ok) error: %v", err)
	}
	if evt.Event != "db.query.users.ok" {
		t.Errorf("event: want db.query.users.ok, got %q", evt.Event)
	}
	if evt.Domain != "db" || evt.Action != "query" || evt.Resource != "users" || evt.Status != "ok" {
		t.Errorf("fields: got domain=%q action=%q resource=%q status=%q",
			evt.Domain, evt.Action, evt.Resource, evt.Status)
	}
}

func TestParity_Event_TooFew(t *testing.T) {
	_, err := Event("too", "few")
	if err == nil {
		t.Error("Event(too,few) should error")
	}
}

func TestParity_Event_TooMany(t *testing.T) {
	_, err := Event("a", "b", "c", "d", "e")
	if err == nil {
		t.Error("Event(a,b,c,d,e) should error")
	}
}

// ── Schema Strict Mode ──────────────────────────────────────────────────────

func TestParity_EventName_LenientAcceptsUppercase(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = false
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("A", "B", "C")
	if err != nil {
		t.Fatalf("lenient EventName should accept uppercase, got error: %v", err)
	}
	if name != "A.B.C" {
		t.Fatalf("expected A.B.C, got %s", name)
	}
}

func TestParity_EventName_LenientAcceptsMixedCase(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = false
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("User", "Login", "Ok")
	if err != nil {
		t.Fatalf("lenient EventName should accept mixed case, got error: %v", err)
	}
	if name != "User.Login.Ok" {
		t.Fatalf("expected User.Login.Ok, got %s", name)
	}
}

func TestParity_EventName_StrictRejectsUppercase(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = origStrict })

	_, err := EventName("User", "login", "ok")
	if err == nil {
		t.Fatal("strict EventName should reject uppercase segment")
	}
}

func TestParity_EventName_StrictAcceptsValid(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("user", "login", "ok")
	if err != nil {
		t.Fatalf("strict EventName should accept valid segments, got: %v", err)
	}
	if name != "user.login.ok" {
		t.Fatalf("expected user.login.ok, got %s", name)
	}
}
