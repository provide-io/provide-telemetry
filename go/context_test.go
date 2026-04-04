// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"sync"
	"testing"
)

func TestBindContext_NewContext(t *testing.T) {
	ctx := context.Background()
	ctx2 := BindContext(ctx, map[string]any{"user": "alice", "req": "123"})
	fields := GetBoundFields(ctx2)
	if fields["user"] != "alice" {
		t.Errorf("expected user=alice, got %v", fields["user"])
	}
	if fields["req"] != "123" {
		t.Errorf("expected req=123, got %v", fields["req"])
	}
}

func TestBindContext_Merges(t *testing.T) {
	ctx := context.Background()
	ctx = BindContext(ctx, map[string]any{"a": 1, "b": 2})
	ctx = BindContext(ctx, map[string]any{"b": 99, "c": 3})
	fields := GetBoundFields(ctx)
	if fields["a"] != 1 {
		t.Errorf("expected a=1, got %v", fields["a"])
	}
	if fields["b"] != 99 {
		t.Errorf("expected b=99 (overridden), got %v", fields["b"])
	}
	if fields["c"] != 3 {
		t.Errorf("expected c=3, got %v", fields["c"])
	}
}

func TestBindContext_DoesNotMutateParent(t *testing.T) {
	parent := context.Background()
	parent = BindContext(parent, map[string]any{"x": 1})
	_ = BindContext(parent, map[string]any{"x": 999, "y": 2})
	fields := GetBoundFields(parent)
	if fields["x"] != 1 {
		t.Errorf("parent was mutated: expected x=1, got %v", fields["x"])
	}
	if _, ok := fields["y"]; ok {
		t.Errorf("parent was mutated: unexpected key y")
	}
}

func TestUnbindContext_RemovesKeys(t *testing.T) {
	ctx := context.Background()
	ctx = BindContext(ctx, map[string]any{"a": 1, "b": 2, "c": 3})
	ctx = UnbindContext(ctx, "a", "c")
	fields := GetBoundFields(ctx)
	if _, ok := fields["a"]; ok {
		t.Errorf("expected a to be removed")
	}
	if _, ok := fields["c"]; ok {
		t.Errorf("expected c to be removed")
	}
	if fields["b"] != 2 {
		t.Errorf("expected b=2, got %v", fields["b"])
	}
}

func TestUnbindContext_MissingKeyIsNoOp(t *testing.T) {
	ctx := context.Background()
	ctx = BindContext(ctx, map[string]any{"a": 1})
	ctx = UnbindContext(ctx, "nonexistent")
	fields := GetBoundFields(ctx)
	if fields["a"] != 1 {
		t.Errorf("expected a=1, got %v", fields["a"])
	}
	if len(fields) != 1 {
		t.Errorf("expected 1 field, got %d", len(fields))
	}
}

func TestClearContext_RemovesAll(t *testing.T) {
	ctx := context.Background()
	ctx = BindContext(ctx, map[string]any{"a": 1, "b": 2})
	ctx = ClearContext(ctx)
	fields := GetBoundFields(ctx)
	if len(fields) != 0 {
		t.Errorf("expected empty fields after clear, got %v", fields)
	}
}

func TestGetBoundFields_EmptyContext(t *testing.T) {
	ctx := context.Background()
	fields := GetBoundFields(ctx)
	if fields == nil {
		t.Error("expected non-nil map from empty context")
	}
	if len(fields) != 0 {
		t.Errorf("expected empty map, got %v", fields)
	}
}

func TestGetBoundFields_ReturnsCopy(t *testing.T) {
	ctx := context.Background()
	ctx = BindContext(ctx, map[string]any{"a": 1})
	fields := GetBoundFields(ctx)
	fields["a"] = 999
	fields["injected"] = true
	// Original context fields should be unaffected.
	original := GetBoundFields(ctx)
	if original["a"] != 1 {
		t.Errorf("context fields mutated via returned copy: expected a=1, got %v", original["a"])
	}
	if _, ok := original["injected"]; ok {
		t.Error("context fields mutated via returned copy: injected key found")
	}
}

func TestGetBoundFields_WrongType(t *testing.T) {
	// Store a non-map value under the fields key to exercise the !ok branch.
	ctx := context.WithValue(context.Background(), _contextFieldsKey, "not-a-map")
	fields := GetBoundFields(ctx)
	if fields == nil {
		t.Error("expected non-nil map when context value has wrong type")
	}
	if len(fields) != 0 {
		t.Errorf("expected empty map when context value has wrong type, got %v", fields)
	}
}

func TestBindContext_GoroutineIsolation(t *testing.T) {
	parent := context.Background()
	parent = BindContext(parent, map[string]any{"shared": "base"})

	var wg sync.WaitGroup
	results := make([]map[string]any, 2)

	wg.Add(2)
	go func() {
		defer wg.Done()
		ctx := BindContext(parent, map[string]any{"goroutine": "A", "shared": "A"})
		results[0] = GetBoundFields(ctx)
	}()
	go func() {
		defer wg.Done()
		ctx := BindContext(parent, map[string]any{"goroutine": "B", "shared": "B"})
		results[1] = GetBoundFields(ctx)
	}()
	wg.Wait()

	// Each goroutine's context must be independent.
	if results[0]["goroutine"] == results[1]["goroutine"] {
		t.Errorf("goroutine fields cross-contaminated: both got goroutine=%v", results[0]["goroutine"])
	}
	if results[0]["shared"] == results[1]["shared"] {
		t.Errorf("shared field cross-contaminated: both got shared=%v", results[0]["shared"])
	}
	// Parent context must remain unmodified.
	parentFields := GetBoundFields(parent)
	if parentFields["shared"] != "base" {
		t.Errorf("parent context mutated: expected shared=base, got %v", parentFields["shared"])
	}
}
