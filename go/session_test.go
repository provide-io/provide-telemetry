// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"testing"
)

const _testBob = "bob"

func TestBindSessionContext(t *testing.T) {
	ctx := context.Background()
	ctx = BindSessionContext(ctx, "sess-abc-123")
	id := GetSessionID(ctx)
	if id != "sess-abc-123" {
		t.Errorf("expected sess-abc-123, got %q", id)
	}
}

func TestGetSessionID_NotSet(t *testing.T) {
	ctx := context.Background()
	id := GetSessionID(ctx)
	if id != "" {
		t.Errorf("expected empty string, got %q", id)
	}
}

func TestClearSessionContext(t *testing.T) {
	ctx := context.Background()
	ctx = BindSessionContext(ctx, "sess-xyz")
	ctx = ClearSessionContext(ctx)
	id := GetSessionID(ctx)
	if id != "" {
		t.Errorf("expected empty string after clear, got %q", id)
	}
}

func TestGetSessionID_WrongType(t *testing.T) {
	// Store a non-string value under the session key to exercise the !ok branch.
	ctx := context.WithValue(context.Background(), _sessionKey, 12345)
	id := GetSessionID(ctx)
	if id != "" {
		t.Errorf("expected empty string when context value has wrong type, got %q", id)
	}
}

func TestSessionContext_DoesNotAffectFields(t *testing.T) {
	ctx := context.Background()
	ctx = BindContext(ctx, map[string]any{"user": _testBob})
	ctx = BindSessionContext(ctx, "sess-999")

	// Session must be set.
	if GetSessionID(ctx) != "sess-999" {
		t.Errorf("expected session sess-999, got %q", GetSessionID(ctx))
	}

	// Bound fields must be unaffected.
	fields := GetBoundFields(ctx)
	if fields["user"] != _testBob {
		t.Errorf("expected user=bob, got %v", fields["user"])
	}
	if _, ok := fields["session"]; ok {
		t.Errorf("session leaked into bound fields: %v", fields)
	}

	// Clearing session must not affect fields.
	ctx = ClearSessionContext(ctx)
	fields = GetBoundFields(ctx)
	if fields["user"] != _testBob {
		t.Errorf("fields changed after ClearSessionContext: expected user=bob, got %v", fields["user"])
	}
}
