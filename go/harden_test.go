// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"
)

type credentials struct {
	Password string `json:"password"`
	Public   string `json:"public"`
	secret   string //nolint:unused // deliberately unexported: must not be traversed
}

type nested struct {
	Inner     credentials       `json:"inner"`
	Tags      map[string]string `json:"tags"`
	Skipped   string            `json:"-"`
	NoTag     int
	Pointered *credentials `json:"pointered"`
}

// TestHardenTraversesTypedContainers is the leak this task exists to close.
//
// Traversal handled exactly two shapes, map[string]any and []any, so anything
// with a concrete element type went to the log verbatim. A []credentials, a
// map[string]string, or a plain struct carried its Password field straight
// through PII redaction untouched.
func TestHardenTraversesTypedContainers(t *testing.T) {
	got := Harden(map[string]any{
		"rows":   []credentials{{Password: "secret", Public: "ok"}},
		"lookup": map[string]string{"api_key": "abcdef", "region": "us-east-1"},
		"single": credentials{Password: "secret", Public: "ok"},
	}, DefaultLimits())

	want := map[string]any{
		"rows":   []any{map[string]any{"password": "secret", "public": "ok"}},
		"lookup": map[string]any{"api_key": "abcdef", "region": "us-east-1"},
		"single": map[string]any{"password": "secret", "public": "ok"},
	}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("harden did not normalize typed containers\n got: %#v\nwant: %#v", got, want)
	}
}

// TestHardenNormalizedOutputIsRedactable is the point of the normalization:
// once a typed value has become map[string]any, the existing PII engine can
// see its sensitive keys.
func TestHardenNormalizedOutputIsRedactable(t *testing.T) {
	ResetPIIRulesForTests()
	hardened, ok := Harden(map[string]any{
		"rows": []credentials{{Password: "secret", Public: "ok"}},
	}, DefaultLimits()).(map[string]any)
	if !ok {
		t.Fatal("expected a map from Harden")
	}

	sanitized := SanitizePayload(hardened, true, 8)
	rows, ok := sanitized["rows"].([]any)
	if !ok || len(rows) != 1 {
		t.Fatalf("expected one normalized row, got %#v", sanitized["rows"])
	}
	row, ok := rows[0].(map[string]any)
	if !ok {
		t.Fatalf("expected a map row, got %#v", rows[0])
	}
	if row["password"] != Redacted {
		t.Errorf("password survived redaction: %#v", row["password"])
	}
	if row["public"] != "ok" {
		t.Errorf("public value was altered: %#v", row["public"])
	}
}

func TestHardenCollapsesCycles(t *testing.T) {
	cycle := map[string]any{"name": "root"}
	cycle["self"] = cycle

	got := Harden(map[string]any{"cycle": cycle}, DefaultLimits())
	want := map[string]any{"cycle": map[string]any{"name": "root", "self": Redacted}}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("cycle was not collapsed\n got: %#v\nwant: %#v", got, want)
	}
}

func TestHardenCollapsesCycleThroughSlice(t *testing.T) {
	type node struct {
		ID       int     `json:"id"`
		Children []*node `json:"children"`
	}
	root := &node{ID: 1}
	root.Children = []*node{root}

	got := Harden(root, DefaultLimits())
	want := map[string]any{"id": int64(1), "children": []any{Redacted}}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("cycle through a typed slice was not collapsed\n got: %#v\nwant: %#v", got, want)
	}
}

func TestHardenTraversalRules(t *testing.T) {
	limits := DefaultLimits()
	cases := []struct {
		name  string
		input any
		want  any
	}{
		{"unexported fields are skipped", credentials{Password: "p", Public: "q", secret: "hidden"},
			map[string]any{"password": "p", "public": "q"}},
		{"json:\"-\" is honored", nested{Skipped: "no", NoTag: 3},
			map[string]any{"inner": map[string]any{"password": "", "public": ""},
				"tags": nil, "NoTag": int64(3), "pointered": nil}},
		{"nil pointer becomes nil", (*credentials)(nil), nil},
		{"nil interface becomes nil", nil, nil},
		{"non-string map keys are unsupported", map[int]string{1: "a"}, Redacted},
		{"channels are unsupported", make(chan int), Redacted},
		{"funcs are unsupported", func() {}, Redacted},
		{"arrays keep order", [3]int{3, 1, 2}, []any{int64(3), int64(1), int64(2)}},
		{"byte slices stay strings", []byte("hello"), "hello"},
		{"floats survive", 1.5, 1.5},
		{"bools survive", true, true},
		{"time formats invariantly", time.Unix(0, 0).UTC(), "1970-01-01T00:00:00Z"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := Harden(tc.input, limits); !reflect.DeepEqual(tc.want, got) {
				t.Errorf("got %#v, want %#v", got, tc.want)
			}
		})
	}
}

func TestHardenAppliesLimits(t *testing.T) {
	limits := Limits{MaxDepth: 2, MaxValueLength: 4, MaxAttrCount: 2}

	if got := Harden(map[string]any{"a": map[string]any{"b": map[string]any{"c": 1}}}, limits); !reflect.DeepEqual(
		map[string]any{"a": map[string]any{"b": Redacted}}, got) {
		t.Errorf("depth limit not applied: %#v", got)
	}
	if got := Harden(map[string]any{"s": "abcdefgh"}, limits); !reflect.DeepEqual(
		map[string]any{"s": "abcd..."}, got) {
		t.Errorf("value length limit not applied: %#v", got)
	}
	hardened, ok := Harden(map[string]any{"a": 1, "b": 2, "c": 3}, limits).(map[string]any)
	if !ok || len(hardened) != 2 {
		t.Errorf("attribute count limit not applied: %#v", hardened)
	}
}

func TestHardenStripsControlCharactersKeepingTabNewlineReturn(t *testing.T) {
	limits := DefaultLimits()
	got := Harden(map[string]any{"s": "a\x00b\x1fc\td\ne\rf"}, limits)
	want := map[string]any{"s": "abc\td\ne\rf"}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("got %#v, want %#v", got, want)
	}
}

// ── extensions to the red-first spec above ───────────────────────────────────

type failingText struct{}

func (failingText) MarshalText() ([]byte, error) { return nil, errors.New("cannot describe myself") }

type wideStruct struct {
	A, B, C int
}

type taggedOptions struct {
	Kept string `json:",omitempty"`
}

// TestHardenRendersSelfDescribingTypes covers the two interfaces that describe
// a value better than its fields do. Traversing *errors.errorString yields an
// empty map — its message lives in an unexported field.
func TestHardenRendersSelfDescribingTypes(t *testing.T) {
	limits := DefaultLimits()
	cases := []struct {
		name  string
		input any
		want  any
	}{
		{"error renders its message", errors.New("boom"), "boom"},
		{"error message is bounded like any string", errors.New("a\x00b"), "ab"},
		{"a TextMarshaler that fails is redacted", failingText{}, Redacted},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := Harden(tc.input, limits); !reflect.DeepEqual(tc.want, got) {
				t.Errorf("got %#v, want %#v", got, tc.want)
			}
		})
	}
}

// TestHardenRemainingKinds covers the leaf kinds the spec cases above do not
// reach, each of which has to widen to its invariant form.
func TestHardenRemainingKinds(t *testing.T) {
	limits := DefaultLimits()
	cases := []struct {
		name  string
		input any
		want  any
	}{
		{"unsigned widens to uint64", uint16(7), uint64(7)},
		{"nil slice becomes nil", []string(nil), nil},
		{"nil byte slice becomes nil", []byte(nil), nil},
		{"empty slice stays a slice", []string{}, []any{}},
		{"untagged json name falls back to the field", taggedOptions{Kept: "x"}, map[string]any{"Kept": "x"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := Harden(tc.input, limits); !reflect.DeepEqual(tc.want, got) {
				t.Errorf("got %#v, want %#v", got, tc.want)
			}
		})
	}
}

// TestHardenAttributeCapAppliesToStructFields pins that a struct is capped the
// same way an object is, in declaration order so the survivors never vary.
func TestHardenAttributeCapAppliesToStructFields(t *testing.T) {
	got := Harden(wideStruct{A: 1, B: 2, C: 3}, Limits{MaxDepth: 8, MaxValueLength: 0, MaxAttrCount: 2})
	want := map[string]any{"A": int64(1), "B": int64(2)}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("got %#v, want %#v", got, want)
	}
}

// TestHardenZeroValueLengthDisablesTruncation is the mode canonicalization runs
// in: a digest must not depend on the cap the logger happened to be using.
func TestHardenZeroValueLengthDisablesTruncation(t *testing.T) {
	long := strings.Repeat("x", _defaultMaxValueLength+10)
	if got := Harden(long, Limits{MaxDepth: 8, MaxValueLength: 0, MaxAttrCount: 0}); got != long {
		t.Errorf("value was truncated with the cap disabled: %d chars", len(got.(string)))
	}
}

// TestHardenAttrsReturnsTheOriginalWhenThereIsNoMap covers the handler-side
// wrapper: a nil attribute map hardens to nil, and the chain downstream indexes
// what it was given.
func TestHardenAttrsReturnsTheOriginalWhenThereIsNoMap(t *testing.T) {
	if got := _hardenAttrs(nil, DefaultLimits()); got != nil {
		t.Errorf("got %#v, want nil", got)
	}
	got := _hardenAttrs(map[string]any{"password": "p"}, DefaultLimits())
	if got["password"] != "p" {
		t.Errorf("got %#v", got)
	}
}

// TestLimitsFromConfigFallsBackPerCap pins that an unset cap means "use the
// default", not "collapse everything": a hand-built TelemetryConfig carries a
// zero SecurityConfig, and a zero MaxDepth would redact every attribute.
func TestLimitsFromConfigFallsBackPerCap(t *testing.T) {
	if got := _limitsFromConfig(&TelemetryConfig{}); got != DefaultLimits() {
		t.Errorf("zero config: got %+v, want %+v", got, DefaultLimits())
	}
	cfg := &TelemetryConfig{Security: SecurityConfig{
		MaxNestingDepth: 3, MaxAttrValueLength: 16, MaxAttrCount: 4,
	}}
	want := Limits{MaxDepth: 3, MaxValueLength: 16, MaxAttrCount: 4}
	if got := _limitsFromConfig(cfg); got != want {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

// TestHardenCollapsesRepeatedSubtrees bounds the other blowup a reference graph
// produces: a subtree shared n times expands n-fold without this, even though
// nothing in it is cyclic. TypeScript pins the same case, so the reference set
// has to span the whole walk rather than the current path.
func TestHardenCollapsesRepeatedSubtrees(t *testing.T) {
	shared := map[string]any{"big": "value"}
	got := Harden(map[string]any{"a": shared, "b": shared}, DefaultLimits())
	want := map[string]any{"a": map[string]any{"big": "value"}, "b": Redacted}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("got %#v, want %#v", got, want)
	}
}

// TestHardenDoesNotConflateEmptyContainers guards the one way pointer identity
// lies: Go gives every zero-size allocation the same address, so two unrelated
// empty slices look like the same reference.
func TestHardenDoesNotConflateEmptyContainers(t *testing.T) {
	got := Harden(map[string]any{"a": []string{}, "b": []string{}, "c": map[string]int{}}, DefaultLimits())
	want := map[string]any{"a": []any{}, "b": []any{}, "c": map[string]any{}}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("got %#v, want %#v", got, want)
	}
}
